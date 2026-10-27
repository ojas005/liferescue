"""Service health and metadata endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from apps.api.config import Settings, get_settings
from apps.api.dependencies import get_orchestrator
from apps.api.schemas import HealthResponse
from packages.domain.ai import NVIDIAAIProvider

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Service status and runtime metadata, including the real AI mode (never the key)."""
    ai = get_orchestrator().ai
    mode, model, last = "mock", None, None
    if isinstance(ai, NVIDIAAIProvider):
        model = ai.model
        last = ai.last_status
        if not ai.is_live_configured() or last.startswith("fallback"):
            mode = "fallback"
        else:
            mode = "live"
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        ai_provider=settings.ai_provider,
        ai_mode=mode,
        ai_model=model,
        ai_last_status=last,
        demo_mode=settings.demo_mode,
        version="1.0.0",
    )
