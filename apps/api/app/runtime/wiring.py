"""Composition helper for the API layer (LR 04): `build_engine(ports) -> RunEngine`.

    from app.runtime.wiring import build_engine
    engine = build_engine(ports)          # LR 04's own `app.ports.Ports` works as-is (duck-typed)

`build_engine` accepts either this module's `Ports` or any object that carries LR 04's attribute
names (`store`, `audit`, `approvals`, `policy`, `registry`, `clock`, `settings`). Missing optional
pieces are filled with runtime defaults:

* model gateway   -> `provider_from_env()` (AI_PROVIDER / LIFERESCUE_MODEL_ADAPTER; mock is refused
                     unless LIFERESCUE_ENV is a dev value; Nebius key from NEBIUS_API_KEY only)
* research        -> `TavilyProvider()` (TAVILY_API_KEY; a missing key makes the research stage
                     record an error and the run continues without research)
* memory          -> `InMemoryMemory`
* tools           -> `RuntimeToolGateway` with `web_search`, `fetch_url` and the simulated
                     `MOCK_TOOLS` discovered under app/workflows/<id>/tools.py

The engine validates every registered workflow against the tool registry at construction, so a
mis-wired workflow fails the process at startup, not at run time.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from contract.errors import ConfigError
from contract.interfaces import (
    ApprovalService,
    AuditLog,
    PolicyEngine,
    ResearchProvider,
    RunEngine,
    RunStore,
    ToolSpec,
    WorkflowRegistry,
)
from contract.models import utcnow

from app.verification import RuntimeVerifier

from .engine import RunLimits, WorkflowEngine
from .events import EventSink
from .memory import InMemoryMemory, Memory
from .mock_tools import discover_mock_tools, register_mock_tools
from .model_gateway import AIProvider, provider_from_env
from .tools import (
    RuntimeToolGateway,
    TavilyProvider,
    register_fetch_url,
    register_web_search,
)


@dataclass(frozen=True)
class Ports:
    """Everything the runtime needs from outside. Names follow contract.interfaces."""

    registry: WorkflowRegistry
    run_store: RunStore
    audit_log: AuditLog
    approval_service: ApprovalService
    policy_engine: PolicyEngine
    model_gateway: AIProvider | None = None  # None -> provider_from_env(env)
    research_provider: ResearchProvider | None = None  # None -> TavilyProvider()
    memory_store: Memory | None = None  # None -> InMemoryMemory()
    tools: RuntimeToolGateway | None = None  # pre-built registry; None -> standard one
    mock_tools: Sequence[ToolSpec] | None = None  # None -> discover_mock_tools()
    event_sink: EventSink | None = None
    clock: Callable[[], datetime] = utcnow
    limits: RunLimits | None = None
    env: Mapping[str, str] | None = None  # None -> os.environ (provider selection)
    auto_advance: bool = True  # False: start() only creates; caller schedules advance()

    @classmethod
    def coerce(cls, ports: Any) -> Ports:
        """Accept this dataclass or LR 04's `app.ports.Ports` (store/audit/approvals/policy/...)."""
        if isinstance(ports, Ports):
            return ports

        def g(*names: str) -> Any:
            return next(
                (getattr(ports, n) for n in names if getattr(ports, n, None) is not None), None
            )

        def req(*names: str) -> Any:
            value = g(*names)
            if value is None:
                raise ConfigError(f"build_engine: ports.{names[0]} is required")
            return value

        env: dict[str, str] | None = None
        settings = getattr(ports, "settings", None)
        if settings is not None:
            env = dict(os.environ)
            if getattr(settings, "model_adapter", None):
                env["AI_PROVIDER"] = str(settings.model_adapter)
            if getattr(settings, "liferescue_env", None):
                env["LIFERESCUE_ENV"] = str(settings.liferescue_env)
        return cls(
            registry=req("registry"),
            run_store=req("run_store", "store"),
            audit_log=req("audit_log", "audit"),
            approval_service=req("approval_service", "approvals"),
            policy_engine=req("policy_engine", "policy"),
            model_gateway=g("model_gateway", "provider"),
            research_provider=g("research_provider", "research"),
            memory_store=g("memory_store", "memory"),
            tools=g("tools"),
            mock_tools=g("mock_tools"),
            event_sink=g("event_sink"),
            clock=g("clock") or utcnow,
            limits=g("limits"),
            env=env,
            auto_advance=bool(getattr(ports, "auto_advance", True)),
        )


def build_standard_tools(
    policy: PolicyEngine,
    approvals: ApprovalService,
    audit: AuditLog,
    research: ResearchProvider,
    mock_tools: Sequence[ToolSpec],
) -> RuntimeToolGateway:
    gateway = RuntimeToolGateway(policy, approvals, audit)
    register_web_search(gateway, research)  # READ
    register_fetch_url(gateway)  # READ, the only user-URL fetcher (safe_fetch)
    register_mock_tools(gateway, mock_tools)  # MOCK_WRITE, always labelled simulated
    return gateway


def build_engine(ports: Ports | Any) -> RunEngine:
    """Build the one `WorkflowEngine` (implements `contract.interfaces.RunEngine`)."""
    p = Ports.coerce(ports)
    provider = p.model_gateway or provider_from_env(p.env)
    tools = p.tools or build_standard_tools(
        p.policy_engine,
        p.approval_service,
        p.audit_log,
        p.research_provider or TavilyProvider(),
        p.mock_tools if p.mock_tools is not None else discover_mock_tools(),
    )
    return WorkflowEngine(
        registry=p.registry,
        store=p.run_store,
        provider=provider,
        tools=tools,
        policy=p.policy_engine,
        approvals=p.approval_service,
        audit=p.audit_log,
        verifier=RuntimeVerifier(provider),
        memory=p.memory_store or InMemoryMemory(),
        event_sink=p.event_sink,
        limits=p.limits,
        clock=p.clock,
        auto_advance=p.auto_advance,
    )


__all__ = ["Ports", "build_engine", "build_standard_tools"]
