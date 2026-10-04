"""CONF-05 digest tamper: an approval is bound to the exact action (run, workflow, step, tool, params, policy version)."""

import pytest

from conf_helpers import VEHICLE, S, approve_all, require, start_to_approval, tool_call_for
from contract.actions import action_for_step
from contract.errors import ApprovalError
from contract.models import ApprovalStatus


def _step_index(run, ap):
    return [s.step_id for s in run.plan].index(ap.step_id)


def test_approval_is_bound_to_the_digest_of_the_planned_action(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    wf = stack.workflow(VEHICLE)
    for ap in stack.approvals(run.run_id):
        step = run.plan[_step_index(run, ap)]
        assert ap.bound_digest == action_for_step(run.run_id, wf, step, run.owner).digest()


def test_changed_params_with_a_valid_approval_are_refused(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    ap = stack.approvals(run.run_id)[0]
    stack.decide(run.run_id, ap.approval_id, True)
    i = _step_index(run, ap)
    with pytest.raises(ApprovalError, match="digest"):
        stack.call_tool(
            tool_call_for(
                stack,
                run,
                i,
                params={**run.plan[i].params, "location": "ATTACKER-CHOSEN-PLACE"},
                approval_id=ap.approval_id,
            )
        )
    assert stack.executed_mock_writes(run.run_id) == []
    assert (
        next(a for a in stack.approvals(run.run_id) if a.approval_id == ap.approval_id).status
        == ApprovalStatus.APPROVED
    ), "a refused attempt must not consume the approval"


def test_approval_for_one_tool_cannot_run_another_tool(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    ap = stack.approvals(run.run_id)[0]
    stack.decide(run.run_id, ap.approval_id, True)
    i = _step_index(run, ap)
    other = "send_message" if run.plan[i].tool_name == "dispatch_tow" else "dispatch_tow"
    with pytest.raises(ApprovalError, match="digest"):
        stack.call_tool(tool_call_for(stack, run, i, tool=other, approval_id=ap.approval_id))
    assert stack.executed_mock_writes(run.run_id) == []


def test_plan_tampered_in_the_store_after_approval_never_executes(stack, vehicle_input):
    require(stack, "supports_store_tamper", "needs direct store access")
    run = start_to_approval(stack, vehicle_input)
    for ap in stack.approvals(run.run_id):  # decide at the service level so the engine has not advanced yet
        stack._run(stack.engine.approvals.decide(ap.approval_id, True, "demo-user"))
    stack.tamper_plan_params(run.run_id, 0, {"location": "ATTACKER-CHOSEN-PLACE"})
    run = stack.advance(run.run_id)
    assert run.state == S.FAILED and "digest" in (run.terminal_reason or "")
    assert stack.executed_mock_writes(run.run_id) == []


def test_finished_run_executed_exactly_the_approved_digests(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    bound = {a.step_id: a.bound_digest for a in stack.approvals(run.run_id)}
    approve_all(stack, run.run_id)
    done = {e.step_id: e.digest for e in stack.executed_mock_writes(run.run_id)}
    assert done == bound
