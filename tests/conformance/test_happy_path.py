"""CONF-01 happy path: INTENT -> ... -> COMPLETED, halting for two human approvals."""

from conf_helpers import MOCK_WRITE_TOOLS, VEHICLE, S, approve_all, start_to_approval, states_seen
from contract.models import ApprovalStatus, EventType, PolicyOutcome, RunState
from contract.run_state_machine import ALLOWED_TRANSITIONS


def test_happy_path_halts_at_approval_then_completes(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    aps = stack.approvals(run.run_id)
    assert len(aps) == 2 and all(a.status == ApprovalStatus.PENDING for a in aps)

    # nothing that writes has run yet; only the READ research ran
    assert stack.executed_mock_writes(run.run_id) == []
    assert {e.tool for e in stack.executed_tools(run.run_id)} == {"web_search"}

    run = stack.decide(run.run_id, aps[0].approval_id, True)
    assert run.state == S.APPROVAL, "one of two approvals is not enough"
    assert stack.executed_mock_writes(run.run_id) == []

    run = stack.decide(run.run_id, aps[1].approval_id, True)
    assert run.state == S.COMPLETED
    assert run.verification is not None and run.verification.passed
    assert [r.tool_name for r in run.results] == list(MOCK_WRITE_TOOLS)
    assert all(r.mocked for r in run.results), "mock_write results must be labelled mocked"
    assert all(a.status == ApprovalStatus.CONSUMED for a in stack.approvals(run.run_id)), "approvals are single use"


def test_happy_path_visits_every_stage_in_order(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    approve_all(stack, run.run_id)
    assert states_seen(stack, run.run_id) == [
        "intent",
        "evidence",
        "research",
        "plan",
        "policy",
        "approval",
        "action",
        "verification",
        "audit",
        "completed",
    ]


def test_every_stage_emits_a_timeline_event_with_increasing_seq(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    approve_all(stack, run.run_id)
    evs = stack.events(run.run_id)
    assert [e.seq for e in evs] == list(range(1, len(evs) + 1))
    kinds = {e.type for e in evs}
    assert {
        EventType.INTENT,
        EventType.EVIDENCE,
        EventType.RESEARCH,
        EventType.PLAN,
        EventType.POLICY,
        EventType.APPROVAL,
        EventType.ACTION,
        EventType.VERIFICATION,
        EventType.AUDIT,
        EventType.STATE_CHANGE,
    } <= kinds


def test_state_changes_follow_the_transition_table(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    approve_all(stack, run.run_id)
    for e in stack.events(run.run_id):
        if e.type == EventType.STATE_CHANGE and "from" in e.payload:
            assert RunState(e.payload["to"]) in ALLOWED_TRANSITIONS[RunState(e.payload["from"])], e.payload


def test_policy_decisions_recorded_per_plan_step(stack, vehicle_input):
    run = start_to_approval(stack, vehicle_input)
    assert [d.step_id for d in run.decisions] == [s.step_id for s in run.plan]
    assert all(d.outcome == PolicyOutcome.NEEDS_APPROVAL for d in run.decisions)
    assert all(d.policy_version and d.action_digest for d in run.decisions)


def test_run_pins_versions(stack, vehicle_input):
    from contract import CONTRACT_VERSION

    run = stack.start(VEHICLE, vehicle_input)
    assert run.contract_version == CONTRACT_VERSION
    assert run.workflow_id == VEHICLE and run.workflow_version == stack.workflow(VEHICLE).version
