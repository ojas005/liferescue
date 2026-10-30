"""Service health and metadata endpoint."""

from __future__ import annotations

import os
import subprocess
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from apps.api.config import Settings, get_settings
from apps.api.dependencies import get_orchestrator
from apps.api.schemas import HealthResponse
from packages.domain.ai import NVIDIAAIProvider
from packages.domain.models import Incident
from packages.domain.research import TavilyResearchTool

router = APIRouter(tags=["Health"])


def _detect_commit_sha() -> str | None:
    for env_var in ("RENDER_GIT_COMMIT", "GIT_COMMIT", "COMMIT_SHA"):
        val = os.environ.get(env_var)
        if val:
            return val.strip()[:12]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        )
        return out.decode().strip()
    except Exception:  # noqa: BLE001
        return None


@router.get("/health", response_model=HealthResponse)
def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
    check_live: bool = Query(
        default=False, description="Run safe minimal live ping tests for AI and Tavily"
    ),
    check_scenario: bool = Query(
        default=False, description="Run one safe synthetic emergency scenario triage"
    ),
) -> HealthResponse:
    """Service status and runtime metadata, including the real AI mode (never the key)."""
    orch = get_orchestrator()
    ai = orch.ai
    tool = orch.research_tool

    ai_mode, ai_model, ai_last = "mock", None, None
    if isinstance(ai, NVIDIAAIProvider):
        ai_model = ai.model
        ai_last = ai.last_status
        if not ai.is_live_configured() or ai_last.startswith("fallback"):
            ai_mode = "fallback"
        else:
            ai_mode = "live"

    res_enabled = isinstance(tool, TavilyResearchTool) and bool(tool._api_key)
    res_mode = "live" if res_enabled else "unavailable"
    res_last = tool.last_status if isinstance(tool, TavilyResearchTool) else None

    diagnostics: dict[str, Any] | None = None

    if check_live:
        diagnostics = {}
        if isinstance(ai, NVIDIAAIProvider):
            ai_test = ai.test_connection()
            diagnostics["ai_connection"] = ai_test
            ai_last = ai_test.get("status")
            ai_mode = "live" if ai_test.get("status") == "live_ok" else "fallback"
        else:
            diagnostics["ai_connection"] = {"configured": False, "mode": "mock"}

        if isinstance(tool, TavilyResearchTool):
            tool_test = tool.test_connection()
            diagnostics["tavily_connection"] = tool_test
            res_last = tool_test.get("status")
            res_mode = "live" if tool_test.get("status") == "live_ok" else "unavailable"
        else:
            diagnostics["tavily_connection"] = {
                "configured": False,
                "mode": "unavailable",
            }

    if check_scenario:
        if diagnostics is None:
            diagnostics = {}
        synth_incident = Incident(
            title="Synthetic Cardiac Emergency Verification",
            description="Patient reports severe sudden crushing substernal chest pressure radiating to left jaw with diaphoresis.",
            location="Verification Suite",
        )
        try:
            analysis = orch.ai.analyze_emergency(synth_incident)
            risk = orch.safety.evaluate_risk(synth_incident, analysis)
            res_payload = (
                orch.research_tool.search(analysis.category, risk.urgency.value)
                if orch.research_tool
                else None
            )
            diagnostics["scenario_test"] = {
                "ai_provider_name": analysis.provider_name,
                "ai_live": "mock_fallback" not in analysis.provider_name,
                "ai_urgency": analysis.urgency.value,
                "ai_severity": analysis.severity_score,
                "ai_summary": analysis.summary,
                "safety_rule": risk.policy_rule_triggered,
                "safety_urgency": risk.urgency.value,
                "escalation_required": risk.requires_escalation,
                "tavily_status": res_payload.get("status") if res_payload else "none",
                "tavily_results_count": len(res_payload.get("results", []))
                if res_payload
                else 0,
                "tavily_results": res_payload.get("results", []) if res_payload else [],
            }
        except Exception as exc:  # noqa: BLE001
            diagnostics["scenario_test"] = {
                "error": type(exc).__name__,
                "detail": str(exc)[:200],
            }

    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        ai_provider=settings.ai_provider,
        ai_mode=ai_mode,
        ai_model=ai_model,
        ai_last_status=ai_last,
        research_enabled=res_enabled,
        research_mode=res_mode,
        research_last_status=res_last,
        commit_sha=_detect_commit_sha(),
        diagnostics=diagnostics,
        demo_mode=settings.demo_mode,
        version="1.0.0",
    )
