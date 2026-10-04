"""HTTP API contract (FastAPI): request/response models. openapi.yaml is GENERATED from these (see openapi_gen.py).

Endpoints (all under /api; ASSUMPTION: no auth in the sprint, single demo user):
  GET  /api/workflows                                  -> list[WorkflowSummary]
  POST /api/runs                {workflow_id, input}   -> 201 RunResponse
  GET  /api/runs/{run_id}                              -> RunResponse
  GET  /api/runs/{run_id}/timeline?after_seq=N&limit=  -> TimelinePage   (POLLING; SSE deferred - ASSUMPTION)
  POST /api/runs/{run_id}/approvals/{approval_id}      {decision, reason} -> RunResponse
  POST /api/runs/{run_id}/cancel                       {reason}           -> RunResponse
  GET  /api/health                                     -> HealthResponse  (ASSUMPTION)
Errors: ErrorResponse with HTTP 404 (unknown workflow/run/approval), 409 (illegal transition / approval not pending / not in approval state),
422 (input fails the workflow's input schema or request validation).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .models import Approval, RunRecord, StrictModel, TimelineEvent


class WorkflowSummary(StrictModel):
    workflow_id: str
    version: str
    title: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema; the FE renders the intake form from it


class CreateRunRequest(StrictModel):
    workflow_id: str
    input: dict[str, Any]
    workflow_version: str | None = None  # default: latest


class RunResponse(StrictModel):
    """Current snapshot. `state` is the pipeline stage; `pending_approvals` is what the UI must show for a decision."""

    run: RunRecord
    approvals: list[Approval] = Field(default_factory=list)  # all approvals of the run, pending first in UI
    last_seq: int = 0  # highest timeline seq so far; poll the timeline with after_seq=last_seq


class TimelinePage(StrictModel):
    run_id: str
    events: list[TimelineEvent]
    next_seq: int  # pass as after_seq on the next poll (equals the last returned seq, or after_seq if none)
    terminal: bool  # True when the run is in a terminal state AND no events remain: stop polling


class ApprovalDecisionRequest(StrictModel):
    decision: Literal["approve", "deny"]
    reason: str | None = Field(default=None, max_length=500)


class CancelRunRequest(StrictModel):
    reason: str | None = Field(default=None, max_length=500)


class ErrorResponse(StrictModel):
    error: str  # stable machine code, e.g. "illegal_transition", "workflow_not_found"
    message: str  # safe, human-readable; never contains secrets or raw provider errors


class HealthResponse(StrictModel):
    status: Literal["ok"]
    contract_version: str
    model_adapter: Literal["nebius", "mock"]


ERROR_CODES: dict[str, int] = {
    "workflow_not_found": 404, "run_not_found": 404, "approval_not_found": 404,
    "illegal_transition": 409, "guard_failed": 409, "approval_invalid": 409, "concurrent_modification": 409,
    "invalid_input": 422,
}
