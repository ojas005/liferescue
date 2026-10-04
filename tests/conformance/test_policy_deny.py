"""CONF-02 policy deny: a DENY decision ends the run in DENIED; nothing that writes executes; no approval is created."""

import pytest
from pydantic import ValidationError

from conf_helpers import VEHICLE, S
from contract.errors import ToolError
from contract.models import EventType, PlanProposal, PlanStepProposal, PolicyOutcome, ToolCall
from lr_support.workflows import vehicle_variant, with_policy_rule, without_policy_rule


def _assert_denied_cleanly(stack, run, rule_id):
    assert run.state == S.DENIED
    assert run.terminal_reason and "policy denied" in run.terminal_reason
    assert stack.executed_mock_writes(run.run_id) == []
    assert stack.approvals(run.run_id) == [], "a denied run must not create approvals"
    pol = [e for e in stack.events(run.run_id) if e.type == EventType.POLICY]
    assert any(e.payload["outcome"] == "deny" and e.payload["rule_id"] == rule_id for e in pol), [
        e.payload for e in pol
    ]
    assert any(d.outcome == PolicyOutcome.DENY and d.rule_id == rule_id for d in run.decisions)
    assert any(r.event_type == "state_change" and r.payload.get("to") == "denied" for r in stack.audit(run.run_id))


def test_default_deny_when_no_rule_matches(stack_factory, vehicle_input):
    stack = stack_factory(definitions=[without_policy_rule("message-needs-approval")])
    run = stack.start(VEHICLE, vehicle_input)
    _assert_denied_cleanly(stack, run, "default-deny")


def test_explicit_deny_rule(stack_factory, vehicle_input):
    rule = {"rule_id": "no-tow", "tool": "dispatch_tow", "outcome": "deny", "risk": "high", "reason": "tow disabled"}
    stack = stack_factory(definitions=[with_policy_rule(rule)])
    run = stack.start(VEHICLE, vehicle_input)
    _assert_denied_cleanly(stack, run, "no-tow")
    assert "tow disabled" in run.terminal_reason


def test_one_denied_step_denies_the_whole_plan(stack_factory, vehicle_input):
    """Plan = [dispatch_tow (denied), send_message (needs approval)] -> DENIED as a whole; the other step is never offered for approval."""
    rule = {"rule_id": "no-tow", "tool": "dispatch_tow", "outcome": "deny", "risk": "high", "reason": "tow disabled"}
    stack = stack_factory(definitions=[with_policy_rule(rule)])
    run = stack.start(VEHICLE, vehicle_input)
    assert run.state == S.DENIED and len(run.decisions) == 2
    assert {d.outcome for d in run.decisions} == {PolicyOutcome.NEEDS_APPROVAL, PolicyOutcome.DENY}


def test_real_write_tools_cannot_be_declared(stack):
    """REAL_WRITE is rejected by the contract itself (sprint: mock-write only)."""
    with pytest.raises(ValidationError, match="REAL_WRITE"):
        vehicle_variant(tools=lambda t: t + [{"tool": "wire_money", "side_effect": "real_write"}])


def test_plan_with_unlisted_tool_fails_closed_before_policy(stack_factory, vehicle_input):
    from contract.fakes import MockModel

    plan = PlanProposal(
        steps=[
            PlanStepProposal(
                action_type="request_tow",
                tool_name="execute_payment",
                params={"amount": 1},
                rationale="model obeyed injected text",
            )
        ]
    )
    stack = stack_factory(model=MockModel({PlanProposal: plan}))
    run = stack.start(VEHICLE, vehicle_input)
    assert run.state == S.FAILED and "does not list" in (run.terminal_reason or "")
    assert stack.executed_mock_writes(run.run_id) == [] and stack.approvals(run.run_id) == []


def test_plan_with_disallowed_action_type_fails_closed(stack_factory, vehicle_input):
    from contract.fakes import MockModel

    plan = PlanProposal(
        steps=[PlanStepProposal(action_type="wire_transfer", tool_name="dispatch_tow", params={}, rationale="x")]
    )
    stack = stack_factory(model=MockModel({PlanProposal: plan}))
    run = stack.start(VEHICLE, vehicle_input)
    assert run.state == S.FAILED and "does not allow" in (run.terminal_reason or "")
    assert stack.executed_mock_writes(run.run_id) == []


def test_gateway_refuses_unregistered_tool(stack, vehicle_input):
    run = stack.start(VEHICLE, vehicle_input)
    with pytest.raises(ToolError):
        stack.call_tool(ToolCall(run_id=run.run_id, step_id="x", tool_name="execute_payment", params={}))
    assert stack.executed_mock_writes(run.run_id) == []
