"""Interactive Demo Scenarios for Hackathon Evaluation (Section 19)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.dependencies import _seed_demo_data, get_db, get_orchestrator
from apps.api.schemas import DemoScenario, RunDemoResponse
from packages.domain.models import AuditEvent
from packages.domain.orchestrator import ResponseOrchestrator
from packages.storage.sqlite_repo import SQLiteDatabase

router = APIRouter(prefix="/demo", tags=["Demo Mode"])

DEMO_SCENARIOS = [
    DemoScenario(
        scenario_id="scenario_medical",
        title="Scenario 1: Acute Medical Emergency",
        category="medical",
        description="Patient experiencing sudden intense chest pressure, left arm pain, and severe shortness of breath.",
        prompt_text="I am experiencing severe crushing chest pain radiating to my left shoulder and jaw, and I am struggling to breathe.",
        location="142 Elmwood Ave, Apartment 3B, Boston MA",
        expected_urgency="critical",
        expected_escalation=True,
    ),
    DemoScenario(
        scenario_id="scenario_accident",
        title="Scenario 2: Highway Vehicle Collision",
        category="accident",
        description="Multi-car collision on interstate with passenger injury and roadway hazard.",
        prompt_text="Two-vehicle high-speed collision on Route 9 North at Exit 14. Smoke is coming from the radiator, passenger has a head laceration, and airbags deployed.",
        location="Route 9 North, Mile Marker 14.2, near Exit 14",
        expected_urgency="high",
        expected_escalation=True,
    ),
    DemoScenario(
        scenario_id="scenario_preparedness",
        title="Scenario 3: Wildfire / Hazmat Evacuation",
        category="fire_hazard",
        description="Rapid brushfire encroaching residential area with heavy smoke.",
        prompt_text="Heavy black smoke and visible flame line approaching the ridge behind our neighborhood. Strong wind, power lines down on the access road.",
        location="880 Pine Ridge Trail, Canyon Vista",
        expected_urgency="critical",
        expected_escalation=True,
    ),
]


@router.get("/scenarios", response_model=list[DemoScenario])
def list_demo_scenarios() -> list[DemoScenario]:
    """Get predefined realistic demonstration scenarios."""
    return DEMO_SCENARIOS


@router.post("/scenarios/{scenario_id}/run", response_model=RunDemoResponse)
def run_demo_scenario(
    scenario_id: str,
    orch: Annotated[ResponseOrchestrator, Depends(get_orchestrator)],
) -> RunDemoResponse:
    """Execute end-to-end workflow for a demo scenario: intake -> triage -> safety policy -> plan -> simulation -> timeline."""
    scenario = next((s for s in DEMO_SCENARIOS if s.scenario_id == scenario_id), None)
    if not scenario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario not found. Available: {[s.scenario_id for s in DEMO_SCENARIOS]}",
        )

    # 1. Create incident
    incident = orch.create_incident(
        title=scenario.title,
        description=scenario.prompt_text,
        user_id="usr_demo",
        location=scenario.location,
        input_type="text",
    )

    # 2. Analyze incident
    analysis, risk = orch.analyze_incident(incident.incident_id)

    # 3. Plan response with safety policy vetting
    orch.plan_response(incident.incident_id)

    # 4. Execute simulated actions
    executed_plan = orch.execute_response(incident.incident_id)

    # 5. Retrieve complete timeline
    timeline = orch.get_timeline(incident.incident_id)

    # Re-read so the response carries the triaged urgency/status (bug: was the pre-analysis copy)
    incident = orch.incident_repo.get(incident.incident_id) or incident

    return RunDemoResponse(
        scenario_id=scenario_id,
        incident=incident,
        analysis=analysis,
        risk=risk,
        plan=executed_plan,
        timeline=timeline,
        research=orch.latest_research(incident.incident_id),
    )


@router.post("/reset")
def reset_demo(
    db: Annotated[SQLiteDatabase, Depends(get_db)],
) -> dict[str, Any]:
    """Safely reset demo data (incidents, timeline events, response plans) for demo user."""
    counts = db.reset_demo_data("usr_demo")
    _seed_demo_data(db, force=True)
    db.record(
        AuditEvent(
            event_type="demo_reset",
            actor="presenter",
            action="reset_demo_state",
            result="success",
            reason="Presenter requested clean demo state",
            details={**counts, "audit_preserved": True},
        )
    )
    return {
        "status": "success",
        "message": "Demo environment reset to pristine baseline.",
        "cleared": counts,
    }
