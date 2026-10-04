"""CONF-07 verification runs after action; CONF-08 audit is complete, append-only-chained and redacted."""

from conf_helpers import VEHICLE, S, approve_all, require, start_to_approval
from contract.models import EventType, SideEffect, ToolSpec


def test_verification_comes_after_every_action_and_passes(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    done = approve_all(stack, run.run_id)
    evs = stack.events(run.run_id)
    actions = [e for e in evs if e.type == EventType.ACTION]
    verifs = [e for e in evs if e.type == EventType.VERIFICATION]
    assert len(actions) == 2 and len(verifs) == 1
    assert verifs[0].seq > max(a.seq for a in actions)
    assert done.verification is not None and done.verification.passed
    assert {c.check_id for c in done.verification.checks} == {
        c.check_id for c in stack.workflow(VEHICLE).verification.checks
    }
    assert verifs[0].payload["passed"] is True


def test_failed_action_tool_fails_the_run_at_verification(stack, vehicle_input):
    require(stack, "supports_tool_override", "needs to replace a tool handler")

    async def broken(params):
        raise RuntimeError("simulated downstream failure")

    stack.override_tool(ToolSpec(name="dispatch_tow", description="broken", side_effect=SideEffect.MOCK_WRITE), broken)
    run = start_to_approval(stack, vehicle_input)
    done = approve_all(stack, run.run_id)
    assert done.state == S.FAILED and "verification failed" in (done.terminal_reason or "")
    assert done.verification is None or not done.verification.passed
    ex = {e.tool: e.status for e in stack.executed_tools(run.run_id)}
    assert ex["dispatch_tow"] == "error"
    evs = stack.events(run.run_id)
    assert any(e.type == EventType.VERIFICATION and e.payload["passed"] is False for e in evs)
    assert not any("Traceback" in str(e.payload) for e in evs), "raw traces must not reach the timeline"


def test_no_verification_before_approvals_are_granted(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    assert not [e for e in stack.events(run.run_id) if e.type in (EventType.ACTION, EventType.VERIFICATION)]


# ---------------------------------------------------------------- audit
def test_audit_covers_the_whole_run(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    done = approve_all(stack, run.run_id)
    assert done.state == S.COMPLETED
    recs = stack.audit(run.run_id)
    kinds = [r.event_type for r in recs]
    assert kinds[0] == "run_created" and kinds[-1] == "state_change" and "run_summary" in kinds
    assert kinds.count("approval_requested") == 2 and kinds.count("approval_decided") == 2
    assert kinds.count("tool_executed") == len(stack.executed_tools(run.run_id)) == 4  # 2 searches + 2 mock writes
    assert kinds.count("tool_policy") == 4, "every tool call is policy-checked, read or write"
    # every state change that reached the timeline is also in the audit log
    tl = [
        (e.payload["from"], e.payload["to"])
        for e in stack.events(run.run_id)
        if e.type == EventType.STATE_CHANGE and "from" in e.payload
    ]
    au = [(r.payload["from"], r.payload["to"]) for r in recs if r.event_type == "state_change"]
    assert tl == au


def test_audit_chain_is_intact_with_contiguous_sequence(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    approve_all(stack, run.run_id)
    assert stack.audit_chain_ok()
    recs = stack.audit(run.run_id)
    assert {r.run_id for r in recs} == {run.run_id}, "single-run stack: the chain below is this run's"
    assert recs[0].prev_hash == "" and [r.prev_hash for r in recs[1:]] == [r.hash for r in recs[:-1]]
    seqs = [r.seq for r in recs]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_every_mock_write_execution_is_preceded_by_its_approval_decision(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    approve_all(stack, run.run_id)
    recs = stack.audit(run.run_id)
    for ex in (r for r in recs if r.event_type == "tool_executed" and r.payload["mocked"]):
        decided = [
            r
            for r in recs
            if r.event_type == "approval_decided"
            and r.payload["digest"] == ex.payload["digest"]
            and r.payload["status"] == "approved"
        ]
        assert decided and decided[0].seq < ex.seq, f"no prior approval for {ex.payload}"


def test_audit_records_who_decided(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    ap = stack.approvals(run.run_id)[0]
    stack.decide(run.run_id, ap.approval_id, False, "no")
    dec = [r for r in stack.audit(run.run_id) if r.event_type == "approval_decided"]
    assert len(dec) == 1 and dec[0].actor.startswith("user:") and dec[0].payload["status"] == "denied"


def test_policy_denied_run_is_audited(stack_factory, vehicle_input):
    from lr_support.workflows import without_policy_rule

    stack = stack_factory(definitions=[without_policy_rule("message-needs-approval")])
    run = stack.start(VEHICLE, vehicle_input)
    kinds = [r.event_type for r in stack.audit(run.run_id)]
    assert (
        kinds[0] == "run_created" and "state_change" in kinds and "tool_executed" in kinds
    )  # research reads still audited
    assert stack.audit_chain_ok()
