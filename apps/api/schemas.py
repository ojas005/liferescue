"""Pydantic API Schemas for LifeRescue REST Endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.domain.models import (
    AIAnalysis,
    Incident,
    IncidentEvent,
    ResponsePlan,
    RiskAssessment,
)


class BaseSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -----------------------------------------------------------------------------
# Incident Schemas
# -----------------------------------------------------------------------------


class CreateIncidentRequest(BaseSchema):
    title: str = Field(
        ..., min_length=1, max_length=200, description="Short headline of the situation"
    )
    description: str = Field(
        ..., min_length=1, max_length=5000, description="Detailed situation report"
    )
    location: str = Field(
        default="",
        max_length=300,
        description="Physical address, landmark, or coordinates",
    )
    input_type: Literal["text", "structured", "voice_transcript", "sensor"] = "text"
    user_id: str = Field(default="usr_demo", max_length=50)


class RespondIncidentRequest(BaseSchema):
    action_ids: list[str] | None = Field(
        default=None, description="Specific actions to execute, or None for all"
    )
    confirm_all: bool = Field(
        default=True, description="Human confirmation confirmation flag"
    )


class IncidentAnalysisResponse(BaseSchema):
    analysis: AIAnalysis
    risk: RiskAssessment
    research: dict[str, Any] | None = (
        None  # KAN-50: untrusted Tavily evidence, display only
    )


class IncidentTimelineResponse(BaseSchema):
    incident_id: str
    events: list[IncidentEvent]


# -----------------------------------------------------------------------------
# Readiness & Profile Schemas
# -----------------------------------------------------------------------------


class UpdateProfileRequest(BaseSchema):
    blood_type: str = Field(default="", max_length=10)
    allergies: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    medical_conditions: list[str] = Field(default_factory=list)
    emergency_instructions: str = Field(default="", max_length=1000)
    primary_language: str = Field(default="en", max_length=10)
    home_address: str = Field(default="", max_length=300)


class CreateContactRequest(BaseSchema):
    name: str = Field(..., min_length=1, max_length=100)
    relationship: str = Field(..., min_length=1, max_length=50)
    phone: str = Field(..., min_length=3, max_length=30)
    email: str = Field(default="", max_length=150)
    is_primary: bool = False
    notify_on_escalation: bool = True


class UpdateContactRequest(BaseSchema):
    name: str | None = Field(default=None, max_length=100)
    relationship: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=150)
    is_primary: bool | None = None
    notify_on_escalation: bool | None = None


# -----------------------------------------------------------------------------
# Demo Scenarios
# -----------------------------------------------------------------------------


class DemoScenario(BaseSchema):
    scenario_id: str
    title: str
    category: str
    description: str
    prompt_text: str
    location: str
    expected_urgency: str
    expected_escalation: bool


class RunDemoResponse(BaseSchema):
    scenario_id: str
    incident: Incident
    analysis: AIAnalysis
    risk: RiskAssessment
    plan: ResponsePlan
    timeline: list[IncidentEvent]
    research: dict[str, Any] | None = (
        None  # KAN-50: untrusted Tavily evidence, display only
    )


# -----------------------------------------------------------------------------
# Health & Errors
# -----------------------------------------------------------------------------


class HealthResponse(BaseSchema):
    status: str
    app_name: str
    ai_provider: str
    ai_mode: str = (
        "mock"  # "mock" | "live" | "fallback" (live provider selected but unavailable)
    )
    ai_model: str | None = None
    ai_last_status: str | None = None
    research_enabled: bool = False
    research_mode: str = "unavailable"
    research_last_status: str | None = None
    commit_sha: str | None = None
    diagnostics: dict[str, Any] | None = None
    demo_mode: bool
    version: str = "1.0.0"


class ErrorResponse(BaseSchema):
    error: str
    detail: str
    request_id: str = ""
