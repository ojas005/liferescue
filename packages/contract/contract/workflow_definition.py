"""WorkflowDefinition: a workflow is CONFIGURATION for the single runtime, never code.

Brief: {workflow_id, intent schema, evidence requirements, research strategy, planning rules,
tools, policy, approval requirements, verification strategy}. `version` is added (ASSUMPTION) so runs can
pin the definition they started with.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .models import PolicyOutcome, RiskLevel, SideEffect, StrictModel, canonical_json, sha256_hex

_ID = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class IntentSpec(StrictModel):
    """What the user may submit and how the model structures it."""

    input_schema: dict[str, Any]  # JSON Schema for POST /api/runs `input`
    instructions: str  # system prompt for the INTENT stage; contains NO policy (policy lives in `policy`)
    entities_schema: dict[str, Any] | None = None  # optional JSON Schema for IntentResult.entities


class EvidenceRequirement(StrictModel):
    key: str
    description: str
    source: Literal["user_input", "tool"]
    input_field: str | None = None  # source=user_input: dotted path inside the run input
    tool: str | None = None  # source=tool: a READ tool listed in `tools`
    required: bool = True

    @model_validator(mode="after")
    def _source_fields(self) -> "EvidenceRequirement":
        if self.source == "user_input" and not self.input_field:
            raise ValueError("source=user_input needs input_field")
        if self.source == "tool" and not self.tool:
            raise ValueError("source=tool needs tool")
        return self


class ResearchStrategy(StrictModel):
    enabled: bool = True
    tool: str = "web_search"  # the Tavily-backed READ tool; always called through the ToolGateway
    queries: list[str] = Field(default_factory=list)  # templates, `{field}` filled from intent entities
    max_results_per_query: int = Field(default=5, ge=1, le=10)
    allowed_domains: list[str] | None = None
    # Research results are untrusted DATA (prompt-injection surface); fixed by the contract, not configurable.

    @model_validator(mode="after")
    def _queries(self) -> "ResearchStrategy":
        if self.enabled and not self.queries:
            raise ValueError("research enabled but no queries")
        if not self.enabled and self.queries:
            raise ValueError("research disabled but queries given")
        return self


class PlanningRules(StrictModel):
    instructions: str  # system prompt for the PLAN stage
    max_steps: int = Field(default=5, ge=1, le=20)
    allowed_action_types: list[str] = Field(min_length=1)


class ToolBinding(StrictModel):
    tool: str
    side_effect: SideEffect  # declared here and checked against the ToolGateway registry at startup


class PolicyRule(StrictModel):
    """Deterministic rule. First match wins. No LLM, no free text matching."""

    rule_id: str
    tool: str | None = None
    side_effect: SideEffect | None = None
    outcome: PolicyOutcome
    risk: RiskLevel
    reason: str

    @model_validator(mode="after")
    def _has_match(self) -> "PolicyRule":
        if self.tool is None and self.side_effect is None:
            raise ValueError("rule must match on tool and/or side_effect")
        return self


class PolicySpec(StrictModel):
    rules: list[PolicyRule]
    default_outcome: Literal["deny"] = "deny"  # fail closed; not configurable

    def version(self) -> str:
        """Policy version = content hash of the rule set (ADR-0005 proposal)."""
        return sha256_hex(canonical_json(self.model_dump(mode="json")))[:16]


class ApprovalRequirements(StrictModel):
    required_for_side_effects: list[SideEffect] = Field(default_factory=lambda: [SideEffect.MOCK_WRITE])
    ttl_seconds: int = Field(default=900, ge=60, le=86400)  # ASSUMPTION: 15 minutes
    # Fixed by the contract: bound to the action digest, single use, decided by the run owner.


class VerificationCheck(StrictModel):
    check_id: str
    kind: Literal["tool_result_status", "evidence_present", "model_assessment"]
    tool: str | None = None  # tool_result_status: that tool's results must all be ok
    evidence_key: str | None = None  # evidence_present
    question: str | None = None  # model_assessment: asked through the ModelGateway

    @model_validator(mode="after")
    def _kind_fields(self) -> "VerificationCheck":
        need = {"tool_result_status": self.tool, "evidence_present": self.evidence_key, "model_assessment": self.question}
        if not need[self.kind]:
            raise ValueError(f"check kind {self.kind} needs its parameter")
        return self


class VerificationStrategy(StrictModel):
    checks: list[VerificationCheck] = Field(min_length=1)
    require_all: bool = True


class WorkflowDefinition(StrictModel):
    workflow_id: str
    version: str
    title: str
    description: str
    intent: IntentSpec
    evidence: list[EvidenceRequirement] = Field(default_factory=list)
    research: ResearchStrategy
    planning: PlanningRules
    tools: list[ToolBinding] = Field(min_length=1)
    policy: PolicySpec
    approvals: ApprovalRequirements = Field(default_factory=ApprovalRequirements)
    verification: VerificationStrategy

    @field_validator("workflow_id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError("workflow_id must match ^[a-z][a-z0-9_]{2,62}$")
        return v

    @field_validator("version")
    @classmethod
    def _ver(cls, v: str) -> str:
        if not _SEMVER.match(v):
            raise ValueError("version must be MAJOR.MINOR.PATCH")
        return v

    @model_validator(mode="after")
    def _cross_checks(self) -> "WorkflowDefinition":
        by_name = {b.tool: b for b in self.tools}
        if len(by_name) != len(self.tools):
            raise ValueError("duplicate tool binding")
        if any(b.side_effect == SideEffect.REAL_WRITE for b in self.tools):
            raise ValueError("REAL_WRITE tools are not allowed in contract 0.x (sprint: mock-write only)")
        keys = [e.key for e in self.evidence]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate evidence key")
        for e in self.evidence:
            if e.source == "tool":
                b = by_name.get(e.tool or "")
                if b is None:
                    raise ValueError(f"evidence {e.key}: tool {e.tool} not in tools")
                if b.side_effect != SideEffect.READ:
                    raise ValueError(f"evidence {e.key}: tool {e.tool} must be a READ tool")
        if self.research.enabled:
            b = by_name.get(self.research.tool)
            if b is None or b.side_effect != SideEffect.READ:
                raise ValueError("research tool must be a READ tool listed in tools")
        for r in self.policy.rules:
            if r.tool is not None and r.tool not in by_name:
                raise ValueError(f"policy rule {r.rule_id}: unknown tool {r.tool}")
        ids = [r.rule_id for r in self.policy.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate policy rule_id")
        # Approval gating consistency: a rule may not ALLOW a side effect that requires approval.
        required = set(self.approvals.required_for_side_effects)
        for r in self.policy.rules:
            effect = r.side_effect or (by_name[r.tool].side_effect if r.tool else None)
            if effect in required and r.outcome == PolicyOutcome.ALLOW:
                raise ValueError(f"policy rule {r.rule_id} allows a side effect that requires approval")
        for c in self.verification.checks:
            if c.kind == "tool_result_status" and c.tool not in by_name:
                raise ValueError(f"check {c.check_id}: unknown tool {c.tool}")
            if c.kind == "evidence_present" and c.evidence_key not in keys:
                raise ValueError(f"check {c.check_id}: unknown evidence key {c.evidence_key}")
        return self

    def tool_side_effect(self, tool: str) -> SideEffect | None:
        for b in self.tools:
            if b.tool == tool:
                return b.side_effect
        return None
