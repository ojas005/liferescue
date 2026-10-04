import itertools

import pytest

from contract.errors import GuardFailed, IllegalTransition
from contract.models import ApprovalStatus, PolicyOutcome, RunState
from contract.run_state_machine import ALLOWED_TRANSITIONS, TERMINAL_STATES, TransitionContext, allowed_next, apply_transition

from .helpers import T0, action, approval, decision, make_run

S = RunState
CTX = dict(now=T0)


def test_table_covers_every_state_and_terminals_have_no_exits():
    assert set(ALLOWED_TRANSITIONS) == set(RunState)
    for s in TERMINAL_STATES:
        assert allowed_next(s) == frozenset()


def test_happy_path_order_matches_brief():
    order = [S.INTENT, S.EVIDENCE, S.RESEARCH, S.PLAN, S.POLICY, S.APPROVAL, S.ACTION, S.VERIFICATION, S.AUDIT, S.COMPLETED]
    for a, b in zip(order, order[1:]):
        assert b in ALLOWED_TRANSITIONS[a]


@pytest.mark.parametrize("src,dst", [(a, b) for a, b in itertools.product(RunState, RunState) if b not in ALLOWED_TRANSITIONS[a]])
def test_every_illegal_transition_is_rejected(src, dst):
    with pytest.raises(IllegalTransition):
        apply_transition(make_run(src), dst, TransitionContext(reason="x", **CTX))


def test_skipping_stages_is_illegal():
    with pytest.raises(IllegalTransition):
        apply_transition(make_run(S.INTENT), S.ACTION)
    with pytest.raises(IllegalTransition):
        apply_transition(make_run(S.PLAN), S.ACTION)


def test_cancel_only_before_action():
    for s in (S.INTENT, S.EVIDENCE, S.RESEARCH, S.PLAN, S.POLICY, S.APPROVAL):
        assert apply_transition(make_run(s), S.CANCELLED, TransitionContext(reason="user", **CTX)).state == S.CANCELLED
    for s in (S.ACTION, S.VERIFICATION, S.AUDIT):
        with pytest.raises(IllegalTransition):
            apply_transition(make_run(s), S.CANCELLED, TransitionContext(reason="user", **CTX))


def test_reason_required_for_failed_denied_cancelled():
    with pytest.raises(GuardFailed):
        apply_transition(make_run(S.PLAN), S.FAILED)
    assert apply_transition(make_run(S.PLAN), S.FAILED, TransitionContext(reason="boom", **CTX)).terminal_reason == "boom"


def test_transition_is_pure_and_bumps_version():
    run = make_run(S.INTENT)
    new = apply_transition(run, S.EVIDENCE, TransitionContext(**CTX))
    assert run.state == S.INTENT and run.version == 0
    assert new.state == S.EVIDENCE and new.version == 1 and new.updated_at == T0


def test_research_gating():
    ev = make_run(S.EVIDENCE)
    with pytest.raises(GuardFailed):
        apply_transition(ev, S.PLAN, TransitionContext(research_enabled=True, **CTX))
    with pytest.raises(GuardFailed):
        apply_transition(ev, S.RESEARCH, TransitionContext(research_enabled=False, **CTX))
    assert apply_transition(ev, S.PLAN, TransitionContext(research_enabled=False, **CTX)).state == S.PLAN
    assert apply_transition(ev, S.RESEARCH, TransitionContext(research_enabled=True, **CTX)).state == S.RESEARCH


# ---- approval-required gating -------------------------------------------------------------

def test_policy_needs_approval_cannot_skip_to_action():
    run = make_run(S.POLICY, [decision("step-1", PolicyOutcome.NEEDS_APPROVAL)])
    with pytest.raises(GuardFailed, match="approval is required"):
        apply_transition(run, S.ACTION, TransitionContext(**CTX))
    assert apply_transition(run, S.APPROVAL, TransitionContext(**CTX)).state == S.APPROVAL


def test_policy_allow_goes_straight_to_action_and_not_to_approval():
    run = make_run(S.POLICY, [decision("step-1", PolicyOutcome.ALLOW)])
    assert apply_transition(run, S.ACTION, TransitionContext(**CTX)).state == S.ACTION
    with pytest.raises(GuardFailed):
        apply_transition(run, S.APPROVAL, TransitionContext(**CTX))


def test_policy_deny_forces_denied():
    run = make_run(S.POLICY, [decision("s1", PolicyOutcome.ALLOW), decision("s2", PolicyOutcome.DENY)])
    for to in (S.ACTION, S.APPROVAL):
        with pytest.raises(GuardFailed):
            apply_transition(run, to, TransitionContext(**CTX))
    assert apply_transition(run, S.DENIED, TransitionContext(reason="denied", **CTX)).state == S.DENIED
    with pytest.raises(GuardFailed):
        apply_transition(make_run(S.POLICY, [decision("s1", PolicyOutcome.ALLOW)]), S.DENIED, TransitionContext(reason="x", **CTX))


def test_policy_transitions_need_decisions():
    with pytest.raises(GuardFailed, match="no policy decisions"):
        apply_transition(make_run(S.POLICY), S.ACTION, TransitionContext(**CTX))


def _gated():
    req = action()
    run = make_run(S.APPROVAL, [decision("step-1", PolicyOutcome.NEEDS_APPROVAL)])
    return run, req


def test_approval_to_action_requires_approved_unexpired_digest_bound_approval():
    run, req = _gated()
    ok = TransitionContext(gated_actions=[req], approvals=[approval(req)], **CTX)
    assert apply_transition(run, S.ACTION, ok).state == S.ACTION


@pytest.mark.parametrize("label,ctx_fn,msg", [
    ("no approval", lambda r: TransitionContext(gated_actions=[r], approvals=[], **CTX), "no approval exists"),
    ("pending", lambda r: TransitionContext(gated_actions=[r], approvals=[approval(r, ApprovalStatus.PENDING)], **CTX), "pending"),
    ("denied", lambda r: TransitionContext(gated_actions=[r], approvals=[approval(r, ApprovalStatus.DENIED)], **CTX), "denied"),
    ("consumed (reuse)", lambda r: TransitionContext(gated_actions=[r], approvals=[approval(r, ApprovalStatus.CONSUMED)], **CTX), "consumed"),
    ("expired", lambda r: TransitionContext(gated_actions=[r], approvals=[approval(r, expires_in=-1)], **CTX), "expired"),
    ("wrong digest", lambda r: TransitionContext(gated_actions=[r], approvals=[approval(r, digest="0" * 64)], **CTX), "different action digest"),
    ("action changed after approval", lambda r: TransitionContext(gated_actions=[action(a=2)], approvals=[approval(r)], **CTX), "different action digest"),
    ("gated list mismatch", lambda r: TransitionContext(gated_actions=[], approvals=[approval(r)], **CTX), "do not match"),
])
def test_approval_gate_rejections(label, ctx_fn, msg):
    run, req = _gated()
    with pytest.raises(GuardFailed, match=msg):
        apply_transition(run, S.ACTION, ctx_fn(req))


def test_every_gated_step_needs_its_own_approval():
    r1, r2 = action("step-1"), action("step-2", b=2)
    run = make_run(S.APPROVAL, [decision("step-1", PolicyOutcome.NEEDS_APPROVAL), decision("step-2", PolicyOutcome.NEEDS_APPROVAL)])
    with pytest.raises(GuardFailed, match="step-2"):
        apply_transition(run, S.ACTION, TransitionContext(gated_actions=[r1, r2], approvals=[approval(r1)], **CTX))
    assert apply_transition(run, S.ACTION, TransitionContext(gated_actions=[r1, r2], approvals=[approval(r1), approval(r2)], **CTX)).state == S.ACTION


def test_digest_is_sensitive_to_every_bound_field():
    base = action()
    assert base.digest() == action().digest()
    for change in ({"params": {"a": 2}}, {"tool_name": "send_message"}, {"policy_version": "v2"}, {"run_id": "r2"}, {"requested_by": "x"},
                   {"workflow_version": "0.2.0"}, {"step_id": "step-9"}):
        assert base.model_copy(update=change).digest() != base.digest()
