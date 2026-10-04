"""Shared data models of the LifeRescue platform contract (pydantic v2).

Everything here is plain data. No I/O, no LLM, no policy logic.
Items marked ASSUMPTION are "PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL".
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base for all contract models: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(obj: Any) -> str:
    """Deterministic JSON used for every digest/hash in the contract."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- enums

class RunState(str, Enum):
    """Run lifecycle. The first nine are the brief's pipeline; the last four are terminal (ASSUMPTION)."""

    INTENT = "intent"
    EVIDENCE = "evidence"
    RESEARCH = "research"
    PLAN = "plan"
    POLICY = "policy"
    APPROVAL = "approval"
    ACTION = "action"
    VERIFICATION = "verification"
    AUDIT = "audit"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset({RunState.COMPLETED, RunState.FAILED, RunState.DENIED, RunState.CANCELLED})


class EventType(str, Enum):
    """Timeline event types. The first nine are the brief's; the last two are ASSUMPTIONS."""

    INTENT = "intent"
    EVIDENCE = "evidence"
    RESEARCH = "research"
    PLAN = "plan"
    POLICY = "policy"
    APPROVAL = "approval"
    ACTION = "action"
    VERIFICATION = "verification"
    AUDIT = "audit"
    STATE_CHANGE = "state_change"
    ERROR = "error"


class SideEffect(str, Enum):
    READ = "read"
    MOCK_WRITE = "mock_write"  # unsafe/unavailable external action, simulated and labelled as mocked
    REAL_WRITE = "real_write"  # reserved; ASSUMPTION: always denied during the sprint


class PolicyOutcome(str, Enum):
    ALLOW = "allow"
    NEEDS_APPROVAL = "needs_approval"
    DENY = "deny"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CONSUMED = "consumed"  # single use: set when the ToolGateway executes the bound action
    REVOKED = "revoked"


# ---------------------------------------------------------------- model gateway data

class Message(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str


class Usage(StrictModel):
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class IntentResult(StrictModel):
    """Structured output of the INTENT stage (platform-generic; domain data goes in `entities`)."""

    summary: str
    category: str
    urgency: RiskLevel = RiskLevel.LOW
    entities: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)


class PlanStepProposal(StrictModel):
    action_type: str
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str


class PlanProposal(StrictModel):
    """Structured output of the PLAN stage. The runtime validates it deterministically (tools, step count)."""

    steps: list[PlanStepProposal]
    summary: str = ""


class AssessmentResult(StrictModel):
    """Structured output of a `model_assessment` verification check."""

    satisfied: bool
    explanation: str


# ---------------------------------------------------------------- run data

class PlanStep(StrictModel):
    step_id: str
    action_type: str
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str


class ActionRequest(StrictModel):
    """One concrete tool action. Its digest is what an approval is bound to."""

    run_id: str
    workflow_id: str
    workflow_version: str
    step_id: str
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    policy_version: str
    requested_by: str

    def digest(self) -> str:
        return sha256_hex(canonical_json(self.model_dump(mode="json")))


class PolicyDecision(StrictModel):
    step_id: str
    outcome: PolicyOutcome
    risk: RiskLevel
    rule_id: str
    reason: str
    policy_version: str
    action_digest: str


class Approval(StrictModel):
    approval_id: str
    run_id: str
    step_id: str
    bound_digest: str  # ActionRequest.digest(); any change to the action needs a new approval
    status: ApprovalStatus = ApprovalStatus.PENDING
    risk: RiskLevel
    summary: str  # human-readable description of the action shown to the approver
    policy_version: str
    requested_at: datetime
    expires_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    reason: str | None = None


class Evidence(StrictModel):
    evidence_id: str
    run_id: str
    key: str  # matches an EvidenceRequirement.key, or "research:<n>"
    kind: Literal["user_input", "tool_result", "research"]
    source: str  # tool name, "user", or URL
    content: dict[str, Any]
    trust: Literal["trusted", "untrusted"] = "untrusted"  # user text, tool output and research are DATA, never instructions; "trusted" only for platform-computed facts
    retrieved_at: datetime
    sha256: str


class ToolSpec(StrictModel):
    name: str
    version: str = "1"
    description: str
    side_effect: SideEffect
    input_schema: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 30
    idempotent: bool = True


class ToolCall(StrictModel):
    run_id: str
    step_id: str
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None  # required by the gateway when the policy outcome is needs_approval


class ToolResult(StrictModel):
    tool_name: str
    status: Literal["ok", "error"]
    output: dict[str, Any] = Field(default_factory=dict)
    mocked: bool = False  # True for MOCK_WRITE tools: the UI must label it "simulated"
    error: str | None = None
    action_digest: str | None = None


class CheckResult(StrictModel):
    check_id: str
    passed: bool
    detail: str


class VerificationResult(StrictModel):
    passed: bool
    checks: list[CheckResult]


class TimelineEvent(StrictModel):
    event_id: str
    run_id: str
    seq: int  # strictly increasing per run, starting at 1
    ts: datetime
    step: RunState  # pipeline stage the event belongs to
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)  # always redacted (see contract.redaction)


class RunRecord(StrictModel):
    run_id: str
    workflow_id: str
    workflow_version: str
    contract_version: str
    owner: str = "demo-user"  # ASSUMPTION: no authentication in the sprint; one demo user
    state: RunState = RunState.INTENT
    input: dict[str, Any]
    intent: IntentResult | None = None
    plan: list[PlanStep] = Field(default_factory=list)
    decisions: list[PolicyDecision] = Field(default_factory=list)
    results: list[ToolResult] = Field(default_factory=list)
    verification: VerificationResult | None = None
    terminal_reason: str | None = None
    version: int = 0  # optimistic-concurrency counter, incremented on each stored change
    created_at: datetime
    updated_at: datetime


class AuditRecord(StrictModel):
    seq: int
    ts: datetime
    run_id: str
    actor: str  # "system", "user:<id>", "model", "tool:<name>"; attribution by statement
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)  # redacted
    prev_hash: str  # ASSUMPTION: hash chain, "" for the first record
    hash: str


class AuditEntryInput(StrictModel):
    run_id: str
    actor: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
