"""Service health and metadata endpoint."""

from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends

from apps.api.config import Settings, get_settings
from apps.api.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Service status and runtime metadata."""
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        ai_provider=settings.ai_provider,
        demo_mode=settings.demo_mode,
        version="1.0.0",
    )
