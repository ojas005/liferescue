"""Small helpers shared by the conformance tests (imported as `helpers`)."""

from __future__ import annotations

from typing import Any

import pytest

from contract.models import ApprovalStatus, EventType, RunRecord, RunState, ToolCall

S = RunState
VEHICLE = "vehicle_breakdown"
MOCK_WRITE_TOOLS = ("dispatch_tow", "send_message")


def states_seen(stack: Any, run_id: str) -> list[str]:
    seen: list[str] = []
    for e in stack.events(run_id):
        to = e.payload.get("to")
        if e.type == EventType.STATE_CHANGE and to and (not seen or seen[-1] != to):
            seen.append(to)
    return seen


def start_to_approval(stack: Any, vehicle_input: dict[str, Any]) -> RunRecord:
    run = stack.start(VEHICLE, vehicle_input)
    assert run.state == S.APPROVAL, run.state
    return run


def approve_all(stack: Any, run_id: str) -> RunRecord:
    run = stack.get_run(run_id)
    for ap in stack.approvals(run_id):
        if ap.status == ApprovalStatus.PENDING:
            run = stack.decide(run_id, ap.approval_id, True)
    return run


def tool_call_for(
    stack: Any,
    run: RunRecord,
    step_index: int,
    *,
    params: dict[str, Any] | None = None,
    tool: str | None = None,
    approval_id: str | None = None,
    run_id: str | None = None,
) -> ToolCall:
    step = run.plan[step_index]
    return ToolCall(
        run_id=run_id or run.run_id,
        step_id=step.step_id,
        tool_name=tool or step.tool_name,
        params=params if params is not None else step.params,
        approval_id=approval_id,
    )


def require(stack: Any, flag: str, why: str) -> None:
    if not getattr(stack, flag, False):
        pytest.skip(f"stack '{stack.kind}' does not support {flag}: {why}")
