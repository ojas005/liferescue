"""Run endpoints. They call the RunEngine port and RunStore/ApprovalService reads only (REPO-LAYOUT s4); every response
is a contract.api_models type; errors are contract exceptions mapped in app/errors.py."""

from __future__ import annotations

import re
from typing import Annotated, Any

from contract.api_models import (
    ApprovalDecisionRequest,
    CancelRunRequest,
    CreateRunRequest,
    ErrorResponse,
    RunResponse,
    TimelinePage,
)
from contract.errors import RunNotFound
from contract.models import TERMINAL_STATES, ApprovalStatus, RunRecord
from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Container, get_container
from app.errors import ApiError, ApprovalNotFound
from app.security.identity import current_actor

router = APIRouter(prefix="/api/runs", tags=["runs"])

_URL = re.compile(r"https?://", re.IGNORECASE)
Ctx = Annotated[Container, Depends(get_container)]
Actor = Annotated[str, Depends(current_actor)]

R404: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse, "description": "Not found"}}
R409: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": "Conflict (illegal transition, approval not pending, concurrent change)",
    }
}
R422: dict[int | str, dict[str, Any]] = {422: {"model": ErrorResponse, "description": "Validation error"}}


def _scan(value: Any, acc: list[int]) -> None:
    """acc = [text chars, url count]."""
    if isinstance(value, str):
        acc[0] += len(value)
        acc[1] += len(_URL.findall(value))
    elif isinstance(value, dict):
        for k, v in value.items():
            _scan(str(k), acc)
            _scan(v, acc)
    elif isinstance(value, list):
        for v in value:
            _scan(v, acc)


def check_input_limits(c: Container, data: dict[str, Any]) -> None:
    """U4: input text <= 20 KB and <= 10 URLs. Reject, never truncate silently."""
    acc = [0, 0]
    _scan(data, acc)
    if acc[0] > c.settings.max_input_text_chars:
        raise ApiError(
            422, "invalid_input", f"Input text exceeds {c.settings.max_input_text_chars} characters."
        )
    if acc[1] > c.settings.max_input_urls:
        raise ApiError(422, "invalid_input", f"Input contains more than {c.settings.max_input_urls} URLs.")


async def snapshot(c: Container, run: RunRecord) -> RunResponse:
    approvals = await c.ports.approvals.list_for_run(run.run_id)
    last = 0
    while True:
        page = await c.ports.store.list_events(run.run_id, after_seq=last, limit=500)
        if not page:
            break
        last = page[-1].seq
        if len(page) < 500:
            break
    return RunResponse(run=run, approvals=approvals, last_seq=last)


async def _load(c: Container, run_id: str) -> RunRecord:
    run = await c.ports.store.get_run(run_id)
    if run is None:
        raise RunNotFound(run_id)
    return run


@router.post(
    "",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createRun",
    summary="Create a run; the runtime starts at INTENT and advances until done or blocked on approval",
    responses={**R404, **R422},
)
async def create_run(body: CreateRunRequest, c: Ctx) -> RunResponse:
    check_input_limits(c, body.input)
    run = await c.engine.start(body.workflow_id, body.input, body.workflow_version)
    return await snapshot(c, run)


@router.get(
    "/{run_id}",
    response_model=RunResponse,
    operation_id="getRun",
    summary="Get a run snapshot with its approvals",
    responses={**R404, **R422},
)
async def get_run(run_id: str, c: Ctx) -> RunResponse:
    return await snapshot(c, await _load(c, run_id))


@router.get(
    "/{run_id}/timeline",
    response_model=TimelinePage,
    operation_id="getTimeline",
    summary="Poll timeline events with seq > after_seq (polling chosen over SSE; PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL)",
    responses={**R404, **R422},
)
async def get_timeline(
    run_id: str,
    c: Ctx,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> TimelinePage:
    run = await _load(c, run_id)
    events = await c.ports.store.list_events(run_id, after_seq=after_seq, limit=limit)
    more = len(events) == limit  # a full page: more events may remain
    return TimelinePage(
        run_id=run_id,
        events=events,
        next_seq=events[-1].seq if events else after_seq,
        terminal=run.state in TERMINAL_STATES and not more,
    )


@router.post(
    "/{run_id}/approvals/{approval_id}",
    response_model=RunResponse,
    operation_id="decideApproval",
    summary="Approve or deny one pending approval (bound to the action digest, single use)",
    responses={**R404, **R409, **R422},
)
async def decide_approval(
    run_id: str, approval_id: str, body: ApprovalDecisionRequest, c: Ctx, actor: Actor
) -> RunResponse:
    run = await _load(c, run_id)
    ap = next((a for a in await c.ports.approvals.list_for_run(run_id) if a.approval_id == approval_id), None)
    if ap is None:
        raise ApprovalNotFound  # also covers an approval id that belongs to another run (no cross-run decisions)
    approve = body.decision == "approve"
    # T5: replaying the SAME decision is an idempotent no-op returning the current state (the first decision stands).
    already = (ApprovalStatus.APPROVED, ApprovalStatus.CONSUMED) if approve else (ApprovalStatus.DENIED,)
    if ap.status in already:
        return await snapshot(c, run)
    run = await c.engine.decide_approval(run_id, approval_id, approve, actor, body.reason)
    return await snapshot(c, run)


@router.post(
    "/{run_id}/cancel",
    response_model=RunResponse,
    operation_id="cancelRun",
    summary="Cancel a run (only before ACTION starts)",
    responses={**R404, **R409, **R422},
)
async def cancel_run(run_id: str, c: Ctx, actor: Actor, body: CancelRunRequest | None = None) -> RunResponse:
    await _load(c, run_id)
    run = await c.engine.cancel(run_id, actor, body.reason if body else None)
    return await snapshot(c, run)
