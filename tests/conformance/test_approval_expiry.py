"""CONF-04 approval expiry: an approval is only valid until expires_at; a late approve does nothing."""

import pytest

from conf_helpers import VEHICLE, S, approve_all, require, start_to_approval
from contract.errors import ApprovalError
from contract.models import ApprovalStatus


def test_approve_just_before_expiry_still_works(stack, vehicle_input):
    require(stack, "supports_clock", "needs a controllable clock")
    run = start_to_approval(stack, vehicle_input)
    ttl = stack.workflow(VEHICLE).approvals.ttl_seconds
    stack.clock.advance(ttl - 1)
    run = approve_all(stack, run.run_id)
    assert run.state == S.COMPLETED


def test_late_approve_is_refused_and_nothing_executes(stack, vehicle_input):
    require(stack, "supports_clock", "needs a controllable clock")
    run = start_to_approval(stack, vehicle_input)
    aps = stack.approvals(run.run_id)
    stack.clock.advance(stack.workflow(VEHICLE).approvals.ttl_seconds + 1)
    with pytest.raises(ApprovalError):
        stack.decide(run.run_id, aps[0].approval_id, True)
    assert all(a.status == ApprovalStatus.EXPIRED for a in stack.approvals(run.run_id))
    assert stack.executed_mock_writes(run.run_id) == []


def test_expired_approvals_end_the_run_denied_on_next_advance(stack, vehicle_input):
    """Documents Q-C6: the run only leaves APPROVAL when something calls `advance` (nothing in the contract does it on a timer)."""
    require(stack, "supports_clock", "needs a controllable clock")
    run = start_to_approval(stack, vehicle_input)
    stack.clock.advance(stack.workflow(VEHICLE).approvals.ttl_seconds + 1)
    assert stack.get_run(run.run_id).state == S.APPROVAL, "still APPROVAL until advance is called (Q-C6)"
    run = stack.advance(run.run_id)
    assert run.state == S.DENIED and "expired" in (run.terminal_reason or "")
    assert stack.executed_mock_writes(run.run_id) == []
    assert any(r.event_type == "state_change" and r.payload.get("to") == "denied" for r in stack.audit(run.run_id))


def test_expired_approval_cannot_be_used_at_the_gateway(stack, vehicle_input):
    require(stack, "supports_clock", "needs a controllable clock")
    from conf_helpers import tool_call_for

    run = start_to_approval(stack, vehicle_input)
    ap = stack.approvals(run.run_id)[0]
    stack.decide(run.run_id, ap.approval_id, True)  # approved while valid
    stack.clock.advance(stack.workflow(VEHICLE).approvals.ttl_seconds + 1)  # then it lapses before use
    step_index = [s.step_id for s in run.plan].index(ap.step_id)
    with pytest.raises(ApprovalError):
        stack.call_tool(tool_call_for(stack, run, step_index, approval_id=ap.approval_id))
    assert stack.executed_mock_writes(run.run_id) == []
