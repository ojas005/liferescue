"""Incident management endpoints (Capabilities A & B)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.dependencies import get_db, get_orchestrator
from apps.api.schemas import (
    CreateIncidentRequest,
    IncidentAnalysisResponse,
    IncidentTimelineResponse,
    RespondIncidentRequest,
)
from packages.domain.models import AIAnalysis, Incident, ResponsePlan
from packages.domain.orchestrator import ResponseOrchestrator, UnknownActionError
from packages.storage.sqlite_repo import SQLiteDatabase

router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.post("", response_model=Incident, status_code=status.HTTP_201_CREATED)
def create_incident(
    req: CreateIncidentRequest,
    orch: Annotated[ResponseOrchestrator, Depends(get_orchestrator)],
) -> Incident:
    """Create a new emergency incident intake."""
    return orch.create_incident(
        title=req.title,
        description=req.description,
        user_id=req.user_id,
        location=req.location,
        input_type=req.input_type,
    )


@router.get("", response_model=list[Incident])
def list_incidents(
    db: Annotated[SQLiteDatabase, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str | None = Query(default=None),
) -> list[Incident]:
    """List recent incidents."""
    return db.list_incidents(limit=limit, user_id=user_id)


@router.get("/{incident_id}", response_model=Incident)
def get_incident(
    incident_id: str,
    db: Annotated[SQLiteDatabase, Depends(get_db)],
) -> Incident:
    """Get single incident by ID."""
    inc = db.get_incident(incident_id)
    if not inc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident not found",
        )
    return inc


@router.post("/{incident_id}/analyze", response_model=IncidentAnalysisResponse)
def analyze_incident(
    incident_id: str,
    orch: Annotated[ResponseOrchestrator, Depends(get_orchestrator)],
) -> IncidentAnalysisResponse:
    """Trigger AI triage and deterministic risk assessment."""
    try:
        analysis, risk = orch.analyze_incident(incident_id)
        return IncidentAnalysisResponse(
            analysis=analysis, risk=risk, research=orch.latest_research(incident_id)
        )
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err))


@router.get("/{incident_id}/analysis", response_model=AIAnalysis)
def get_incident_analysis(
    incident_id: str,
    db: Annotated[SQLiteDatabase, Depends(get_db)],
) -> AIAnalysis:
    """Get recorded AI analysis for an incident."""
    analysis = db.get_analysis(incident_id)
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis for this incident has not been performed yet",
        )
    return analysis


@router.post("/{incident_id}/respond", response_model=ResponsePlan)
def respond_incident(
    incident_id: str,
    req: RespondIncidentRequest,
    orch: Annotated[ResponseOrchestrator, Depends(get_orchestrator)],
) -> ResponsePlan:
    """Plan and execute/simulate governed response actions."""
    try:
        plan = orch.execute_response(incident_id, action_ids=req.action_ids)
        return plan
    except UnknownActionError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err))


@router.get("/{incident_id}/timeline", response_model=IncidentTimelineResponse)
def get_incident_timeline(
    incident_id: str,
    orch: Annotated[ResponseOrchestrator, Depends(get_orchestrator)],
    db: Annotated[SQLiteDatabase, Depends(get_db)],
) -> IncidentTimelineResponse:
    """Get full chronological timeline and audit trail for an incident."""
    inc = db.get_incident(incident_id)
    if not inc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident not found",
        )
    events = orch.get_timeline(incident_id)
    return IncidentTimelineResponse(incident_id=incident_id, events=events)
