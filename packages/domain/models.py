"""LifeRescue Unified Domain Models.

Represents all core entities across the three core capabilities:
Capability A — Emergency Understanding & Triage
Capability B — Emergency Action / Response Coordination
Capability C — Personal Emergency Readiness / Prevention
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    """Return current UTC timestamp with timezone."""
    return datetime.now(timezone.utc)


def generate_id(prefix: str = "") -> str:
    """Generate a prefixed unique identifier."""
    uid = uuid.uuid4().hex[:12]
    return f"{prefix}_{uid}" if prefix else uid


class StrictModel(BaseModel):
    """Base model that rejects unrecognized extra fields for safety."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class UrgencyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    OPEN = "open"
    ANALYZING = "analyzing"
    TRIAGED = "triaged"
    RESPONDING = "responding"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class ResponseActionType(str, Enum):
    CALL_EMERGENCY_SERVICES = "call_emergency_services"
    NOTIFY_CONTACT = "notify_contact"
    DISPLAY_INSTRUCTIONS = "display_instructions"
    PREPARE_SUMMARY = "prepare_summary"
    BROADCAST_LOCATION = "broadcast_location"
    SOUND_ALARM = "sound_alarm"
    LOCK_DOORS = "lock_doors"
    UNLOCK_DOORS = "unlock_doors"
    CUSTOM = "custom"


class ResponseActionStatus(str, Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    SIMULATED = "simulated"
    FAILED = "failed"
    CANCELLED = "cancelled"


# -----------------------------------------------------------------------------
# User & Preparedness (Capability C)
# -----------------------------------------------------------------------------


class User(StrictModel):
    user_id: str = Field(default_factory=lambda: generate_id("usr"))
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=150)
    phone: str = Field(default="", max_length=30)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class EmergencyContact(StrictModel):
    contact_id: str = Field(default_factory=lambda: generate_id("cnt"))
    user_id: str
    name: str = Field(..., min_length=1, max_length=100)
    relationship: str = Field(..., min_length=1, max_length=50)
    phone: str = Field(..., min_length=3, max_length=30)
    email: str = Field(default="", max_length=150)
    is_primary: bool = False
    notify_on_escalation: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class EmergencyProfile(StrictModel):
    user_id: str
    blood_type: str = Field(default="", max_length=10)
    allergies: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    medical_conditions: list[str] = Field(default_factory=list)
    emergency_instructions: str = Field(default="", max_length=1000)
    primary_language: str = Field(default="en", max_length=10)
    home_address: str = Field(default="", max_length=300)
    updated_at: datetime = Field(default_factory=utcnow)


class ReadinessCheck(StrictModel):
    check_id: str
    category: Literal["profile", "contacts", "medical", "instructions"]
    title: str
    description: str
    passed: bool
    importance: Literal["recommended", "critical"] = "recommended"


class ReadinessAssessment(StrictModel):
    user_id: str
    score: int = Field(ge=0, le=100)
    status: Literal["poor", "moderate", "good", "excellent"]
    checks: list[ReadinessCheck] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    assessed_at: datetime = Field(default_factory=utcnow)


# -----------------------------------------------------------------------------
# Incident & Triage (Capability A)
# -----------------------------------------------------------------------------


class Incident(StrictModel):
    incident_id: str = Field(default_factory=lambda: generate_id("inc"))
    user_id: str = "usr_demo"
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)
    input_type: Literal["text", "structured", "voice_transcript", "sensor"] = "text"
    location: str = Field(default="", max_length=300)
    status: IncidentStatus = IncidentStatus.OPEN
    urgency: UrgencyLevel = UrgencyLevel.MEDIUM
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


class AIAnalysis(StrictModel):
    analysis_id: str = Field(default_factory=lambda: generate_id("ana"))
    incident_id: str
    summary: str = Field(..., max_length=1000)
    category: str = Field(
        ..., max_length=100
    )  # e.g., "medical", "accident", "fire", "security"
    urgency: UrgencyLevel
    severity_score: int = Field(ge=1, le=10)  # 1-10 scale
    confidence: float = Field(ge=0.0, le=1.0)
    immediate_threat: bool = False
    extracted_facts: dict[str, Any] = Field(default_factory=dict)
    missing_critical_info: list[str] = Field(default_factory=list)
    recommended_immediate_steps: list[str] = Field(default_factory=list)
    provider_name: str = "mock"
    analyzed_at: datetime = Field(default_factory=utcnow)


class RiskAssessment(StrictModel):
    assessment_id: str = Field(default_factory=lambda: generate_id("rsk"))
    incident_id: str
    urgency: UrgencyLevel
    requires_escalation: bool
    escalation_reason: str = ""
    policy_rule_triggered: str = ""
    medical_disclaimer: str = (
        "LifeRescue provides AI emergency assistance and safety triage guidance. "
        "It does not replace professional emergency services or certified medical diagnosis."
    )
    assessed_at: datetime = Field(default_factory=utcnow)


# -----------------------------------------------------------------------------
# Action & Response Coordination (Capability B)
# -----------------------------------------------------------------------------


class ResponseAction(StrictModel):
    action_id: str = Field(default_factory=lambda: generate_id("act"))
    action_type: ResponseActionType
    title: str = Field(..., max_length=150)
    description: str = Field(..., max_length=1000)
    is_escalation: bool = False
    requires_confirmation: bool = False
    status: ResponseActionStatus = ResponseActionStatus.PENDING
    payload: dict[str, Any] = Field(default_factory=dict)
    mocked: bool = True  # Always True in demo/mock mode
    result_message: str = ""
    executed_at: datetime | None = None


class ResponsePlan(StrictModel):
    plan_id: str = Field(default_factory=lambda: generate_id("pln"))
    incident_id: str
    rationale: str = Field(..., max_length=1000)
    actions: list[ResponseAction] = Field(default_factory=list)
    approved_by_policy: bool = True
    policy_notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class IncidentEvent(StrictModel):
    event_id: str = Field(default_factory=lambda: generate_id("evt"))
    incident_id: str
    seq: int
    timestamp: datetime = Field(default_factory=utcnow)
    event_type: str = Field(..., max_length=50)
    actor: str = Field(
        ..., max_length=50
    )  # e.g., "user", "ai_agent", "safety_policy", "orchestrator"
    summary: str = Field(..., max_length=300)
    payload: dict[str, Any] = Field(default_factory=dict)


# -----------------------------------------------------------------------------
# Auditing (Security & Auditability)
# -----------------------------------------------------------------------------


class AuditEvent(StrictModel):
    event_id: str = Field(default_factory=lambda: generate_id("aud"))
    timestamp: datetime = Field(default_factory=utcnow)
    event_type: str = Field(..., max_length=60)
    actor: str = Field(..., max_length=60)
    incident_id: str | None = None
    action: str = Field(..., max_length=100)
    result: str = Field(..., max_length=50)  # "success", "rejected", "denied", "error"
    reason: str = Field(default="", max_length=500)
    request_id: str = Field(default="", max_length=64)
    details: dict[str, Any] = Field(default_factory=dict)
