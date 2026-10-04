"""LR 01 decision: human approval is required before ANY mock_write side-effect action.
READ tools (Tavily web_search, safe_fetch) are policy-checked and audited but need no human approval.
(Tests assert exactly that rule, on the contract fakes now and on the real stack later.)"""

import pytest

from conf_helpers import MOCK_WRITE_TOOLS, VEHICLE, S, approve_all, start_to_approval
from contract.errors import PolicyDenied
from contract.models import (
    ApprovalStatus,
    PlanProposal,
    PlanStepProposal,
    PolicyOutcome,
    SideEffect,
    ToolCall,
    ToolSpec,
)
from lr_support.workflows import vehicle_variant, with_read_tool


def _plan_only(*steps):
    return PlanProposal(
        steps=[PlanStepProposal(action_type=a, tool_name=t, params=p, rationale="r") for a, t, p in steps]
    )


# ---------------------------------------------------------------- mock_write needs approval
def test_every_mock_write_step_is_gated_and_gets_an_approval(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    wf = stack.workflow(VEHICLE)
    gated = {
        s.step_id for s, d in zip(run.plan, run.decisions, strict=True) if d.outcome == PolicyOutcome.NEEDS_APPROVAL
    }
    mock_write_steps = {s.step_id for s in run.plan if wf.tool_side_effect(s.tool_name) == SideEffect.MOCK_WRITE}
    assert mock_write_steps and gated == mock_write_steps
    assert {a.step_id for a in stack.approvals(run.run_id)} == mock_write_steps


@pytest.mark.parametrize(
    "tool,params", [("dispatch_tow", {"location": "Pune"}), ("send_message", {"to": "emergency-contact", "text": "hi"})]
)
def test_mock_write_never_executes_before_its_approval(stack_factory, vehicle_input, tool, params):
    from contract.fakes import MockModel

    stack = stack_factory(
        model=MockModel(
            {PlanProposal: _plan_only(("request_tow" if tool == "dispatch_tow" else "notify_contact", tool, params))}
        )
    )
    run = stack.start(VEHICLE, vehicle_input)
    assert run.state == S.APPROVAL
    assert stack.executed_mock_writes(run.run_id) == [], "nothing may write before a human decides"
    (ap,) = stack.approvals(run.run_id)
    assert ap.status == ApprovalStatus.PENDING
    done = stack.decide(run.run_id, ap.approval_id, True)
    assert done.state == S.COMPLETED
    (ex,) = stack.executed_mock_writes(run.run_id)
    assert ex.tool == tool and ex.mocked and ex.digest == ap.bound_digest


def test_a_denied_approval_means_the_mock_write_never_runs(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    ap = stack.approvals(run.run_id)[0]
    run = stack.decide(run.run_id, ap.approval_id, False, "no")
    assert run.state == S.DENIED
    assert stack.executed_mock_writes(run.run_id) == []


def test_gateway_itself_refuses_a_mock_write_without_approval(stack, vehicle_input):
    """Defence in depth: even a caller that skips the engine cannot execute a mock_write without an approval id."""
    run = stack.start(VEHICLE, vehicle_input)
    for tool in MOCK_WRITE_TOOLS:
        with pytest.raises(PolicyDenied):
            stack.call_tool(ToolCall(run_id=run.run_id, step_id="direct-1", tool_name=tool, params={"x": 1}))
    assert stack.executed_mock_writes(run.run_id) == []


def test_contract_rejects_a_workflow_that_allows_mock_write_by_policy(stack):
    """A policy rule may not ALLOW a side effect that requires approval (definition-time guard)."""
    from pydantic import ValidationError

    rules = [
        {"rule_id": "mw-allow", "side_effect": "mock_write", "outcome": "allow", "risk": "low", "reason": "x"},
        {"rule_id": "read-ok", "side_effect": "read", "outcome": "allow", "risk": "low", "reason": "x"},
    ]
    with pytest.raises(ValidationError, match="requires approval"):
        vehicle_variant(policy=lambda p: {**p, "rules": rules})


@pytest.mark.xfail(
    strict=True,
    reason="G1 (QA finding): a WorkflowDefinition with approvals.required_for_side_effects=[] plus an ALLOW rule for "
    "mock_write is accepted by the contract, and its mock_write tools then execute with NO approval. LR 01's rule needs "
    "mock_write to ALWAYS require approval (validator should refuse an empty/partial list). Flips to XPASS when LR 03 fixes it.",
)
def test_workflow_cannot_opt_out_of_mock_write_approval(stack_factory, vehicle_input):
    rules = [
        {"rule_id": "mw-allow", "side_effect": "mock_write", "outcome": "allow", "risk": "low", "reason": "x"},
        {"rule_id": "read-ok", "side_effect": "read", "outcome": "allow", "risk": "low", "reason": "x"},
    ]
    try:
        wf = vehicle_variant(
            approvals=lambda a: {**a, "required_for_side_effects": []}, policy=lambda p: {**p, "rules": rules}
        )
    except Exception:
        return  # definition refused: the desired behaviour
    stack = stack_factory(definitions=[wf])
    run = stack.start(VEHICLE, vehicle_input)
    assert stack.executed_mock_writes(run.run_id) == [], "mock_write executed without any human approval"


# ---------------------------------------------------------------- read tools: checked and audited, no human approval
def test_read_tool_runs_without_approval_but_is_policy_checked_and_audited(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    reads = [e for e in stack.executed_tools(run.run_id) if e.tool == "web_search"]
    assert reads, "research must have run the READ tool before the approval gate"
    assert all(not e.mocked and e.status == "ok" for e in reads)
    audit = stack.audit(run.run_id)
    checks = [r for r in audit if r.event_type == "tool_policy" and r.actor == "tool:web_search"]
    assert len(checks) == len(reads), "every READ call is policy-checked"
    assert all(r.payload["outcome"] == "allow" and r.payload["rule_id"] == "read-ok" for r in checks)
    assert all(r.payload["digest"] for r in checks)
    # no approval ever existed for a read step
    assert all(not a.step_id.startswith(("research-", "evidence-")) for a in stack.approvals(run.run_id))


def test_read_only_plan_completes_with_zero_approvals(stack_factory, vehicle_input):
    from contract.fakes import MockModel

    model = MockModel(
        {PlanProposal: _plan_only(("lookup", "web_search", {"query": "roadside assistance Pune", "max_results": 2}))}
    )
    stack = stack_factory(model=model)
    run = stack.start(VEHICLE, vehicle_input)
    assert run.state == S.COMPLETED, (run.state, run.terminal_reason)
    assert stack.approvals(run.run_id) == []
    assert [d.outcome for d in run.decisions] == [PolicyOutcome.ALLOW]
    assert any(
        r.event_type == "tool_policy" and r.payload["step_id"] == run.plan[0].step_id for r in stack.audit(run.run_id)
    )


def test_gateway_runs_a_read_tool_without_approval_id(stack, vehicle_input):
    run = stack.start(VEHICLE, vehicle_input)
    res = stack.call_tool(
        ToolCall(
            run_id=run.run_id,
            step_id="direct-read",
            tool_name="web_search",
            params={"query": "tow Pune", "max_results": 1},
        )
    )
    assert res.status == "ok" and not res.mocked
    assert any(r.event_type == "tool_policy" and r.payload["step_id"] == "direct-read" for r in stack.audit(run.run_id))


def test_second_read_tool_safe_fetch_needs_no_approval_either(stack_factory, vehicle_input):
    """safe_fetch is a READ tool (LR 06). Not in the contract fakes, so a fake one is registered; on the real stack this uses the real tool."""
    from contract.fakes import MockModel

    async def fake_fetch(params):
        return {"status": "fetched", "url": params.get("url"), "text": "synthetic page"}

    spec = ToolSpec(name="safe_fetch", description="fetch a public page (fake)", side_effect=SideEffect.READ)
    plan = _plan_only(("fetch", "safe_fetch", {"url": "https://example.test/tow-info"}))
    stack = stack_factory(
        definitions=[with_read_tool("safe_fetch", "fetch")],
        model=MockModel({PlanProposal: plan}),
        extra_tools=[(spec, fake_fetch)],
    )
    run = stack.start(VEHICLE, vehicle_input)
    assert run.state == S.COMPLETED and stack.approvals(run.run_id) == []
    ex = [e for e in stack.executed_tools(run.run_id) if e.tool == "safe_fetch"]
    assert len(ex) == 1 and not ex[0].mocked
    assert any(
        r.event_type == "tool_policy" and r.actor == "tool:safe_fetch" and r.payload["outcome"] == "allow"
        for r in stack.audit(run.run_id)
    )


def test_a_read_tool_is_never_labelled_mocked_and_a_mock_write_always_is(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    done = approve_all(stack, run.run_id)
    by_tool = {e.tool: e.mocked for e in stack.executed_tools(run.run_id)}
    assert by_tool["web_search"] is False and by_tool["dispatch_tow"] is True and by_tool["send_message"] is True
    assert all(r.mocked for r in done.results)
