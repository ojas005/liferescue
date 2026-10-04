"""LifeRescue Main FastAPI Application Entrypoint."""

from __future__ import annotations

import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from apps.api.config import Settings, get_settings
from apps.api.dependencies import init_dependencies
from apps.api.middleware import SecurityAndCorrelationMiddleware, setup_secure_logging
from apps.api.routes import (
    audit_router,
    demo_router,
    health_router,
    incidents_router,
    readiness_router,
)

logger = logging.getLogger("liferescue.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()

    # Configure secure redacting logging
    setup_secure_logging()

    app = FastAPI(
        title="LifeRescue Emergency Coordination Platform",
        description=(
            "AI-assisted emergency triage, deterministic safety policy vetting, "
            "response coordination, and personal readiness platform."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # 1. CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Security and correlation middleware
    app.add_middleware(SecurityAndCorrelationMiddleware)

    # 3. Exception handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        req_id = getattr(request.state, "request_id", "")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.__class__.__name__,
                "detail": str(exc.detail),
                "request_id": req_id,
            },
            headers={"X-Request-ID": req_id},
        )

    # 4. Include REST API routers
    app.include_router(incidents_router)
    app.include_router(readiness_router)
    app.include_router(demo_router)
    app.include_router(audit_router)
    app.include_router(health_router)

    # 5. Static files & Web UI
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_home():
            return FileResponse(static_dir / "index.html")

    # 6. Initialize DB and seed demo data on app creation
    init_dependencies(cfg)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    cfg = get_settings()
    uvicorn.run("apps.api.main:app", host=cfg.host, port=cfg.port, reload=True)
