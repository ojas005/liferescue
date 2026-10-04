"""Run state machine contract. THE ONLY place that decides whether a run may change state.

Pipeline (brief): Intent -> Evidence -> Research -> Plan -> Policy -> Approval -> Action -> Verification -> Audit.
Terminal states COMPLETED / FAILED / DENIED / CANCELLED are PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL.

Rules enforced by `apply_transition` (the runtime must call it for every state change, nothing else may set `state`):
  * only transitions in ALLOWED_TRANSITIONS; terminal states have no exits;
  * POLICY -> ACTION only when every policy decision is ALLOW (no approval needed);
  * POLICY -> APPROVAL only when at least one decision is NEEDS_APPROVAL and none is DENY;
  * POLICY -> DENIED when any decision is DENY;
  * APPROVAL -> ACTION only when each gated step has an APPROVED, unexpired approval whose bound digest equals
    the digest of the action that will run (single use is enforced when the ToolGateway consumes it);
  * EVIDENCE -> PLAN (skipping RESEARCH) only when the workflow's research is disabled;
  * CANCELLED only before ACTION starts (ASSUMPTION: an action in flight is not cancelled mid-way).
"""
from __future__ import annotations

from datetime import datetime
from typing import Mapping

from pydantic import Field

from .errors import GuardFailed, IllegalTransition
from .models import (
    TERMINAL_STATES, ActionRequest, Approval, ApprovalStatus, PolicyDecision, PolicyOutcome, RunRecord, RunState,
    StrictModel, utcnow,
)

__all__ = ["RunState", "TERMINAL_STATES", "ALLOWED_TRANSITIONS", "TransitionContext", "apply_transition", "allowed_next"]

S = RunState

ALLOWED_TRANSITIONS: Mapping[RunState, frozenset[RunState]] = {
    S.INTENT: frozenset({S.EVIDENCE, S.FAILED, S.CANCELLED}),
    S.EVIDENCE: frozenset({S.RESEARCH, S.PLAN, S.FAILED, S.CANCELLED}),
    S.RESEARCH: frozenset({S.PLAN, S.FAILED, S.CANCELLED}),
    S.PLAN: frozenset({S.POLICY, S.FAILED, S.CANCELLED}),
    S.POLICY: frozenset({S.APPROVAL, S.ACTION, S.DENIED, S.FAILED, S.CANCELLED}),
    S.APPROVAL: frozenset({S.ACTION, S.DENIED, S.FAILED, S.CANCELLED}),
    S.ACTION: frozenset({S.VERIFICATION, S.FAILED}),
    S.VERIFICATION: frozenset({S.AUDIT, S.FAILED}),
    S.AUDIT: frozenset({S.COMPLETED, S.FAILED}),
    S.COMPLETED: frozenset(),
    S.FAILED: frozenset(),
    S.DENIED: frozenset(),
    S.CANCELLED: frozenset(),
}


class TransitionContext(StrictModel):
    """Facts the guards need. The caller supplies them from the stores; the machine trusts nothing else."""

    research_enabled: bool = True
    gated_actions: list[ActionRequest] = Field(default_factory=list)  # actions that need approval, as they WILL run
    approvals: list[Approval] = Field(default_factory=list)
    reason: str | None = None  # required for FAILED / DENIED / CANCELLED
    now: datetime = Field(default_factory=utcnow)


def allowed_next(state: RunState) -> frozenset[RunState]:
    return ALLOWED_TRANSITIONS[state]


def _check_policy_guards(run: RunRecord, to: RunState) -> None:
    outcomes = [d.outcome for d in run.decisions]
    if not outcomes:
        raise GuardFailed("no policy decisions recorded for this run")
    if to == S.DENIED and PolicyOutcome.DENY not in outcomes and run.state == S.POLICY:
        raise GuardFailed("POLICY -> DENIED needs at least one DENY decision")
    if run.state != S.POLICY:
        return
    if to in (S.APPROVAL, S.ACTION) and PolicyOutcome.DENY in outcomes:
        raise GuardFailed("a DENY decision exists; the run must go to DENIED")
    if to == S.ACTION and PolicyOutcome.NEEDS_APPROVAL in outcomes:
        raise GuardFailed("approval is required; POLICY -> ACTION is not allowed")
    if to == S.APPROVAL and PolicyOutcome.NEEDS_APPROVAL not in outcomes:
        raise GuardFailed("no decision needs approval; POLICY -> APPROVAL is not allowed")


def _check_approval_guards(run: RunRecord, ctx: TransitionContext) -> None:
    gated_ids = {d.step_id for d in run.decisions if d.outcome == PolicyOutcome.NEEDS_APPROVAL}
    if not gated_ids:
        raise GuardFailed("APPROVAL -> ACTION without any gated step")
    by_step = {a.step_id: a for a in ctx.gated_actions}
    if set(by_step) != gated_ids:
        raise GuardFailed("gated actions in context do not match the policy decisions")
    for step_id in gated_ids:
        matching = [a for a in ctx.approvals if a.step_id == step_id and a.run_id == run.run_id]
        if not matching:
            raise GuardFailed(f"step {step_id}: no approval exists")
        ap = matching[-1]
        if ap.status != ApprovalStatus.APPROVED:
            raise GuardFailed(f"step {step_id}: approval is {ap.status.value}, not approved")
        if ap.expires_at <= ctx.now:
            raise GuardFailed(f"step {step_id}: approval expired")
        if ap.bound_digest != by_step[step_id].digest():
            raise GuardFailed(f"step {step_id}: approval is bound to a different action digest")


def apply_transition(run: RunRecord, to: RunState, ctx: TransitionContext | None = None) -> RunRecord:
    """Return a NEW RunRecord in state `to`, or raise IllegalTransition / GuardFailed. Never mutates `run`."""
    ctx = ctx or TransitionContext()
    if run.state in TERMINAL_STATES:
        raise IllegalTransition(f"run is terminal ({run.state.value})")
    if to not in ALLOWED_TRANSITIONS[run.state]:
        raise IllegalTransition(f"{run.state.value} -> {to.value} is not allowed")
    if run.state == S.EVIDENCE and to == S.PLAN and ctx.research_enabled:
        raise GuardFailed("research is enabled for this workflow; EVIDENCE -> PLAN is not allowed")
    if run.state == S.EVIDENCE and to == S.RESEARCH and not ctx.research_enabled:
        raise GuardFailed("research is disabled for this workflow; EVIDENCE -> RESEARCH is not allowed")
    if run.state == S.POLICY and to in (S.APPROVAL, S.ACTION, S.DENIED):
        _check_policy_guards(run, to)
    if run.state == S.APPROVAL and to == S.ACTION:
        _check_approval_guards(run, ctx)
    if to in (S.FAILED, S.DENIED, S.CANCELLED) and not ctx.reason:
        raise GuardFailed(f"a reason is required to enter {to.value}")
    updates: dict[str, object] = {"state": to, "updated_at": ctx.now, "version": run.version + 1}
    if to in (S.FAILED, S.DENIED, S.CANCELLED):
        updates["terminal_reason"] = ctx.reason
    return run.model_copy(update=updates)
