"""Ports (typing.Protocol) of the single LifeRescue runtime. Adapters implement these; nothing else talks to the outside.

One-runtime rules (see CONTRACT-README.md):
  * the ONLY model calls go through ModelGateway; the ONLY tool/network calls go through ToolGateway;
  * the ONLY thing that sets RunRecord.state is run_state_machine.apply_transition;
  * policy is code (PolicyEngine) and never lives in prompts.
All methods are async except PolicyEngine and config helpers (pure and deterministic).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Literal, Protocol, Sequence, TypeVar, runtime_checkable

from pydantic import BaseModel

from .errors import ConfigError
from .models import (
    ActionRequest, Approval, AuditEntryInput, AuditRecord, EventType, Evidence, Message, PolicyDecision, RunRecord,
    RunState, StrictModel, TimelineEvent, ToolCall, ToolResult, ToolSpec, Usage, VerificationResult,
)
from .workflow_definition import PolicySpec, VerificationStrategy, WorkflowDefinition

T = TypeVar("T", bound=BaseModel)


# ------------------------------------------------------------------ ModelGateway

class StructuredResult(StrictModel):
    """Generic envelope: `output` is validated against the requested pydantic type by the gateway."""

    output: Any  # an instance of the requested schema; typed as Any to keep the envelope non-generic
    model: str
    adapter: Literal["nebius", "mock"]
    usage: Usage = Usage()


@runtime_checkable
class ModelGateway(Protocol):
    """Customer inference ONLY via the Nebius/NVIDIA path (OpenAI-compatible). `mock` is for dev/tests only."""

    adapter_kind: Literal["nebius", "mock"]

    async def complete_structured(
        self, schema: type[T], messages: Sequence[Message], *, purpose: str, run_id: str | None = None,
        max_tokens: int = 1024, timeout_s: float = 30.0,
    ) -> StructuredResult:
        """Return output validated as `schema` (raise ModelSchemaError if it cannot be), or raise ModelUnavailable.
        Never returns raw model text to domain code. Never logs prompts/responses in full (usage + ids only)."""
        ...


def assert_model_adapter_allowed(environment: str, adapter_kind: str) -> None:
    """Config guard (call at startup and in the release gate): the mock adapter must be impossible in production."""
    if environment in ("production", "prod", "staging") and adapter_kind != "nebius":
        raise ConfigError(f"model adapter '{adapter_kind}' is not allowed in environment '{environment}'")
    if adapter_kind not in ("nebius", "mock"):
        raise ConfigError(f"unknown model adapter '{adapter_kind}'")


def model_adapter_from_env(env: dict[str, str] | None = None) -> str:
    """ASSUMPTION: LIFERESCUE_MODEL_ADAPTER selects the adapter; the key is read by the adapter from NEBIUS_API_KEY only."""
    e = os.environ if env is None else env
    kind = e.get("LIFERESCUE_MODEL_ADAPTER", "nebius")
    assert_model_adapter_allowed(e.get("LIFERESCUE_ENV", "production"), kind)
    return kind


# ------------------------------------------------------------------ ToolGateway / research

@runtime_checkable
class ToolGateway(Protocol):
    """Registry + the single execution path for tools. `call` re-checks policy itself (independent of the engine)."""

    def list_tools(self) -> list[ToolSpec]: ...

    def get_tool(self, name: str) -> ToolSpec | None: ...

    async def call(self, call: ToolCall, workflow: WorkflowDefinition, requested_by: str) -> ToolResult:
        """Order: tool exists -> policy evaluate -> deny => PolicyDenied -> needs_approval => consume approval
        (digest-bound, single use) -> run with timeout -> normalize output -> audit. MOCK_WRITE results have mocked=True."""
        ...


class SearchQuery(StrictModel):
    query: str
    max_results: int = 5
    allowed_domains: list[str] | None = None


class SearchResult(StrictModel):
    title: str
    url: str
    snippet: str
    score: float | None = None


@runtime_checkable
class ResearchProvider(Protocol):
    """Tavily adapter port. Used only BY the `web_search` READ tool inside the ToolGateway.
    Results are untrusted data. URL fetching (if ever added) must be SSRF-safe and is a separate gated tool."""

    async def search(self, query: SearchQuery) -> list[SearchResult]: ...


# ------------------------------------------------------------------ PolicyEngine

@runtime_checkable
class PolicyEngine(Protocol):
    """Deterministic, synchronous, outside the LLM. Unknown tool or no matching rule => DENY."""

    def evaluate(self, request: ActionRequest, spec: PolicySpec, tool: ToolSpec | None) -> PolicyDecision: ...

    def policy_version(self, spec: PolicySpec) -> str: ...


# ------------------------------------------------------------------ ApprovalService

@runtime_checkable
class ApprovalService(Protocol):
    async def create(self, request: ActionRequest, decision: PolicyDecision, summary: str, ttl_seconds: int) -> Approval: ...

    async def get(self, approval_id: str) -> Approval | None: ...

    async def list_for_run(self, run_id: str) -> list[Approval]: ...

    async def decide(self, approval_id: str, approve: bool, decided_by: str, reason: str | None = None) -> Approval:
        """PENDING -> APPROVED | DENIED. Raise ApprovalError if not pending or expired (-> EXPIRED)."""
        ...

    async def revoke_pending(self, run_id: str) -> list[Approval]:
        """PENDING/APPROVED-but-unconsumed -> REVOKED (used on cancel)."""
        ...

    async def consume(self, approval_id: str, expected_digest: str) -> Approval:
        """APPROVED -> CONSUMED exactly once. Raise ApprovalError on wrong digest, expired, not approved, or reuse."""
        ...


# ------------------------------------------------------------------ Verifier

@runtime_checkable
class Verifier(Protocol):
    async def verify(
        self, run: RunRecord, strategy: VerificationStrategy, evidence: Sequence[Evidence], results: Sequence[ToolResult],
    ) -> VerificationResult:
        """A claimed outcome without confirmation is not complete. `model_assessment` checks go through ModelGateway."""
        ...


# ------------------------------------------------------------------ AuditLog

@runtime_checkable
class AuditLog(Protocol):
    """Append-only BY INTERFACE: there is no update or delete. Hash chain (prev_hash/hash) is an ASSUMPTION."""

    async def append(self, entry: AuditEntryInput) -> AuditRecord: ...

    async def list_for_run(self, run_id: str) -> list[AuditRecord]: ...

    async def verify_chain(self) -> bool: ...


# ------------------------------------------------------------------ RunStore / registry

@runtime_checkable
class WorkflowRegistry(Protocol):
    def list(self) -> list[WorkflowDefinition]: ...

    def get(self, workflow_id: str, version: str | None = None) -> WorkflowDefinition | None: ...


@runtime_checkable
class RunStore(Protocol):
    """Persistence port (PostgreSQL in the product). Optimistic concurrency via RunRecord.version."""

    async def create_run(self, run: RunRecord) -> RunRecord: ...

    async def get_run(self, run_id: str) -> RunRecord | None: ...

    async def save_run(self, run: RunRecord, expected_version: int) -> RunRecord:
        """Raise ConcurrentModification if the stored version != expected_version."""
        ...

    async def append_event(self, run_id: str, step: RunState, type: EventType, payload: dict[str, Any], ts: datetime | None = None) -> TimelineEvent:
        """Assign seq = previous + 1 atomically per run. Payload must already be redacted."""
        ...

    async def list_events(self, run_id: str, after_seq: int = 0, limit: int = 200) -> list[TimelineEvent]: ...

    async def add_evidence(self, evidence: Evidence) -> None: ...

    async def list_evidence(self, run_id: str) -> list[Evidence]: ...


# ------------------------------------------------------------------ RunEngine (the ONE runtime)

@runtime_checkable
class RunEngine(Protocol):
    """The single orchestrator, implemented once by the agent engineer in apps/api/app/runtime.
    The API layer calls ONLY this. `contract.fakes.engine.ReferenceRunEngine` is a test double, never a product runtime."""

    async def start(self, workflow_id: str, input: dict[str, Any], workflow_version: str | None = None) -> RunRecord:
        """Validate input against the workflow's input schema, create the run (state INTENT) and begin advancing."""
        ...

    async def advance(self, run_id: str) -> RunRecord:
        """Advance until the run is terminal or blocked on a human approval."""
        ...

    async def decide_approval(self, run_id: str, approval_id: str, approve: bool, decided_by: str, reason: str | None = None) -> RunRecord: ...

    async def cancel(self, run_id: str, requested_by: str, reason: str | None = None) -> RunRecord: ...
