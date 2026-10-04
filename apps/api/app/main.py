"""Composition root: the ONLY place that wires adapters into ports (REPO-LAYOUT s1/s4).

    uvicorn app.main:create_app --factory

Startup is fail-closed: the model adapter must be allowed for LIFERESCUE_ENV (assert_model_adapter_allowed), a Nebius
adapter needs its key in the environment, every workflow schema must be valid. Test doubles from ``contract.fakes`` are
NEVER imported here (arch_check R3); tests inject an engine through ``run_engine_factory``.
"""

from __future__ import annotations

import importlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from contract.errors import ConfigError
from contract.interfaces import RunEngine, assert_model_adapter_allowed
from contract.models import utcnow
from contract.validation import check_workflow_schemas
from contract.workflow_definition import WorkflowDefinition
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from sqlalchemy import Engine

from app import __version__
from app.api import health, runs, workflows
from app.api.deps import Container
from app.api.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from app.approvals.sql_service import SqlApprovalService
from app.audit.sql_audit import SqlAuditLog
from app.db.run_store import SqlRunStore
from app.db.session import make_engine, make_sessionmaker
from app.errors import register_error_handlers
from app.logging_config import configure_logging, request_id_var
from app.placeholder_engine import PlaceholderRunEngine
from app.policy.engine import DeterministicPolicyEngine
from app.ports import Ports
from app.security import keys
from app.security.identity import ACTOR_HEADER
from app.settings import DEFAULT_DATABASE_URL, Settings, get_settings
from app.workflows.registry import StaticWorkflowRegistry, default_definitions

log = logging.getLogger("liferescue.api")

RunEngineFactory = Callable[[Ports], RunEngine]


def _runtime_engine(ports: Ports) -> RunEngine:
    """LR 06 provides app/runtime/wiring.py::build_engine(ports) -> RunEngine. Until then: placeholder (no advancing)."""
    try:
        wiring = importlib.import_module("app.runtime.wiring")
    except ModuleNotFoundError as e:
        if e.name not in ("app.runtime", "app.runtime.wiring"):
            raise
        log.warning(
            "runtime_not_wired",
            extra={"detail": "app.runtime.wiring missing; runs are created but not advanced"},
        )
        return PlaceholderRunEngine(ports)
    engine: RunEngine = wiring.build_engine(ports)
    return engine


def _custom_openapi(app: FastAPI) -> Callable[[], dict[str, object]]:
    def build() -> dict[str, object]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title="LifeRescue Run API",
            version=_contract_version(),
            routes=app.routes,
            description="One generic run API for every workflow. No authentication in the sprint "
            "(PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL).",
        )
        comps = schema.get("components", {}).get("schemas", {})
        for name in ("HTTPValidationError", "ValidationError"):
            comps.pop(name, None)
        app.openapi_schema = schema
        return schema

    return build


def _contract_version() -> str:
    from contract import CONTRACT_VERSION

    return CONTRACT_VERSION


def create_app(
    settings: Settings | None = None,
    *,
    db_engine: Engine | None = None,
    definitions: list[WorkflowDefinition] | None = None,
    run_engine_factory: RunEngineFactory | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    # ---- fail-closed startup checks -------------------------------------------------------------
    assert_model_adapter_allowed(settings.liferescue_env, settings.model_adapter)
    if settings.model_adapter == "nebius":
        keys.require_key(
            "NEBIUS_API_KEY"
        )  # presence only; the adapter reads the value through app.security.keys
    if (
        db_engine is None
        and not settings.docs_enabled  # production / prod / staging
        and settings.database_url == DEFAULT_DATABASE_URL
    ):
        # The built-in default is the local dev database with a throwaway password and the schema-owner user.
        raise ConfigError("DATABASE_URL must be set explicitly when LIFERESCUE_ENV is production or staging")
    redactor = configure_logging(
        settings.log_level, keys.known_secret_values([settings.database_password() or ""])
    )
    defs = definitions if definitions is not None else default_definitions()
    for d in defs:
        check_workflow_schemas(d)

    # ---- adapters ------------------------------------------------------------------------------
    engine = db_engine or make_engine(settings.database_url)
    sf = make_sessionmaker(engine)
    ports = Ports(
        settings=settings,
        registry=StaticWorkflowRegistry(defs),
        store=SqlRunStore(sf, redactor),
        audit=SqlAuditLog(sf, redactor),
        approvals=SqlApprovalService(sf, redactor),
        policy=DeterministicPolicyEngine(),
        redactor=redactor,
        clock=utcnow,
    )
    run_engine = (run_engine_factory or _runtime_engine)(ports)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "api_start",
            extra={
                "env": settings.liferescue_env,
                "model_adapter": settings.model_adapter,
                "keys_present": keys.key_status(),
                "broker": keys.BROKER_MODULE_NAME,
            },
        )
        yield
        engine.dispose()

    app = FastAPI(
        title="LifeRescue API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.container = Container(settings=settings, ports=ports, engine=run_engine)
    app.state.sessionmaker = sf
    app.openapi = _custom_openapi(app)  # type: ignore[method-assign]

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", ACTOR_HEADER, "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID", "")
        if not (0 < len(rid) <= 64 and rid.replace("-", "").replace("_", "").isalnum()):
            rid = uuid.uuid4().hex
        request.state.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            log.info(
                "request",
                extra={"method": request.method, "path": request.url.path, "status": response.status_code},
            )
            return response
        finally:
            request_id_var.reset(token)

    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(workflows.router)
    app.include_router(runs.router)
    return app
