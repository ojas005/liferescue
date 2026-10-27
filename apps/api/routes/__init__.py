"""LifeRescue API Routers."""

from apps.api.routes.audit import router as audit_router
from apps.api.routes.demo import router as demo_router
from apps.api.routes.health import router as health_router
from apps.api.routes.incidents import router as incidents_router
from apps.api.routes.readiness import router as readiness_router

__all__ = [
    "audit_router",
    "demo_router",
    "health_router",
    "incidents_router",
    "readiness_router",
]
