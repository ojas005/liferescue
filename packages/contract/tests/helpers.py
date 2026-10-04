from datetime import datetime, timedelta, timezone

from contract.models import (
    ActionRequest, Approval, ApprovalStatus, PolicyDecision, PolicyOutcome, RiskLevel, RunRecord, RunState,
)

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def make_run(state: RunState = RunState.INTENT, decisions: list[PolicyDecision] | None = None) -> RunRecord:
    return RunRecord(run_id="r1", workflow_id="vehicle_breakdown", workflow_version="0.1.0", contract_version="0.1.0",
                     input={"description": "x"}, state=state, decisions=decisions or [], created_at=T0, updated_at=T0)


def decision(step: str, outcome: PolicyOutcome) -> PolicyDecision:
    return PolicyDecision(step_id=step, outcome=outcome, risk=RiskLevel.HIGH, rule_id="r", reason="r", policy_version="v", action_digest="d")


def action(step: str = "step-1", **params) -> ActionRequest:
    return ActionRequest(run_id="r1", workflow_id="vehicle_breakdown", workflow_version="0.1.0", step_id=step, tool_name="dispatch_tow",
                         params=params or {"a": 1}, policy_version="v", requested_by="demo-user")


def approval(req: ActionRequest, status: ApprovalStatus = ApprovalStatus.APPROVED, expires_in: int = 600, digest: str | None = None) -> Approval:
    return Approval(approval_id=f"ap-{req.step_id}", run_id=req.run_id, step_id=req.step_id, bound_digest=digest or req.digest(), status=status,
                    risk=RiskLevel.HIGH, summary="s", policy_version="v", requested_at=T0, expires_at=T0 + timedelta(seconds=expires_in))
