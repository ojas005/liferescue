"""CONF-06 approval reuse: single use, run-bound, decision-bound."""

import pytest

from conf_helpers import S, approve_all, start_to_approval, tool_call_for
from contract.errors import ApprovalError, PolicyDenied
from contract.models import ApprovalStatus


def _idx(run, ap):
    return [s.step_id for s in run.plan].index(ap.step_id)


def test_consumed_approval_cannot_be_replayed(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    aps = stack.approvals(run.run_id)
    done = approve_all(stack, run.run_id)
    assert done.state == S.COMPLETED
    before = len(stack.executed_mock_writes(run.run_id))
    for ap in aps:
        with pytest.raises(ApprovalError):
            stack.call_tool(tool_call_for(stack, done, _idx(done, ap), approval_id=ap.approval_id))
    assert len(stack.executed_mock_writes(run.run_id)) == before == 2


def test_repeating_a_decision_has_no_second_effect(stack, vehicle_input):
    """Contract fake raises ApprovalError; LR 04/LR 08 T5 want an idempotent no-op. Both are acceptable HERE; what is not
    acceptable is a second execution or a status change. The disagreement itself is open question Q-C5 (finding F2)."""
    run = start_to_approval(stack, vehicle_input)
    aps = stack.approvals(run.run_id)
    done = approve_all(stack, run.run_id)
    statuses = {a.approval_id: a.status for a in stack.approvals(run.run_id)}
    for ap in aps:
        try:
            again = stack.decide(run.run_id, ap.approval_id, True)
            assert again.state == done.state
        except ApprovalError:
            pass
    assert {a.approval_id: a.status for a in stack.approvals(run.run_id)} == statuses
    assert len(stack.executed_mock_writes(run.run_id)) == 2


def test_opposite_decision_after_approve_is_refused(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    ap = stack.approvals(run.run_id)[0]
    stack.decide(run.run_id, ap.approval_id, True)
    with pytest.raises(ApprovalError):
        stack.decide(run.run_id, ap.approval_id, False)
    assert (
        next(a for a in stack.approvals(run.run_id) if a.approval_id == ap.approval_id).status
        == ApprovalStatus.APPROVED
    )


def test_approval_of_run_a_cannot_authorise_the_same_action_in_run_b(stack, vehicle_input):
    a = start_to_approval(stack, vehicle_input)
    ap = stack.approvals(a.run_id)[0]
    stack.decide(a.run_id, ap.approval_id, True)
    b = start_to_approval(stack, vehicle_input)  # same input, same plan, different run
    i = _idx(a, ap)
    with pytest.raises(ApprovalError, match="digest"):
        stack.call_tool(tool_call_for(stack, b, i, approval_id=ap.approval_id))
    assert stack.executed_mock_writes(b.run_id) == []


def test_approval_id_of_run_a_cannot_be_decided_under_run_b(stack, vehicle_input):
    a = start_to_approval(stack, vehicle_input)
    b = start_to_approval(stack, vehicle_input)
    foreign = stack.approvals(a.run_id)[0]
    with pytest.raises(ApprovalError):
        stack.decide(b.run_id, foreign.approval_id, True)
    assert (
        next(x for x in stack.approvals(a.run_id) if x.approval_id == foreign.approval_id).status
        == ApprovalStatus.PENDING
    )


def test_pending_denied_and_unknown_approvals_authorise_nothing(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    aps = stack.approvals(run.run_id)
    pending, to_deny = aps[0], aps[1]
    stack.decide(run.run_id, to_deny.approval_id, False, "no")
    for approval_id in (pending.approval_id, to_deny.approval_id, "00000000-0000-0000-0000-000000000000"):
        with pytest.raises(ApprovalError):
            stack.call_tool(tool_call_for(stack, run, 0, approval_id=approval_id))
    assert stack.executed_mock_writes(run.run_id) == []


def test_mock_write_without_any_approval_id_is_refused(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    with pytest.raises(PolicyDenied, match="approval"):
        stack.call_tool(tool_call_for(stack, run, 0, approval_id=None))
    assert stack.executed_mock_writes(run.run_id) == []
