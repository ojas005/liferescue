"""CONF-03 cancel: allowed only before ACTION; revokes pending approvals; nothing executes afterwards."""

import pytest

from conf_helpers import S, approve_all, start_to_approval
from contract.errors import ApprovalError, IllegalTransition, RunNotFound
from contract.models import ApprovalStatus


def test_cancel_while_waiting_for_approval(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    run = stack.cancel(run.run_id, "changed my mind")
    assert run.state == S.CANCELLED and run.terminal_reason == "changed my mind"
    assert all(a.status == ApprovalStatus.REVOKED for a in stack.approvals(run.run_id)), (
        "pending approvals must be revoked"
    )
    assert stack.executed_mock_writes(run.run_id) == []
    assert any(
        r.event_type == "state_change" and r.payload.get("to") == "cancelled" and r.actor.startswith("user:")
        for r in stack.audit(run.run_id)
    )


def test_late_approval_after_cancel_is_refused_and_executes_nothing(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    aps = stack.approvals(run.run_id)
    stack.cancel(run.run_id)
    with pytest.raises(ApprovalError):
        stack.decide(run.run_id, aps[0].approval_id, True)
    assert stack.get_run(run.run_id).state == S.CANCELLED
    assert stack.executed_mock_writes(run.run_id) == []


def test_cancel_after_completion_is_illegal(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    run = approve_all(stack, run.run_id)
    assert run.state == S.COMPLETED
    with pytest.raises(IllegalTransition):
        stack.cancel(run.run_id)
    assert stack.get_run(run.run_id).state == S.COMPLETED


def test_cancel_twice_is_illegal(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    stack.cancel(run.run_id)
    with pytest.raises(IllegalTransition):
        stack.cancel(run.run_id)


def test_cancel_unknown_run(stack):
    with pytest.raises(RunNotFound):
        stack.cancel("does-not-exist")
