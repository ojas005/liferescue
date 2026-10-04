"""Deterministic PolicyEngine (contract.interfaces.PolicyEngine). No LLM, no I/O, synchronous.

Properties (ADR-0005 simplified; SECURITY T1, T3, T4):
  * deny by default: unknown tool, no matching rule, unknown side effect -> DENY;
  * REAL_WRITE is always DENY (contract 0.x);
  * first matching rule wins, but a rule can never make a non-read tool run without approval: any ALLOW for a
    MOCK_WRITE action is upgraded to NEEDS_APPROVAL (defence in depth on top of the WorkflowDefinition validator);
  * the request must name the tool it is evaluated against and carry the policy version of the spec, otherwise DENY
    (stale/forged request);
  * ANY exception while evaluating -> DENY (fail closed). The decision carries rule_id and ``action_digest``
    (hash of the exact inputs) so the timeline/audit can show what was decided.
"""

from __future__ import annotations

from contract.models import ActionRequest, PolicyDecision, PolicyOutcome, RiskLevel, SideEffect, ToolSpec
from contract.workflow_definition import PolicySpec


class DeterministicPolicyEngine:
    def policy_version(self, spec: PolicySpec) -> str:
        return spec.version()

    def evaluate(self, request: ActionRequest, spec: PolicySpec, tool: ToolSpec | None) -> PolicyDecision:
        try:
            return self._evaluate(request, spec, tool)
        except Exception:  # noqa: BLE001 - fail closed, never leak the exception text
            return PolicyDecision(
                step_id=getattr(request, "step_id", "unknown"),
                outcome=PolicyOutcome.DENY,
                risk=RiskLevel.HIGH,
                rule_id="policy-error",
                reason="policy evaluation failed; denied (fail closed)",
                policy_version="unknown",
                action_digest="unknown",
            )

    def _evaluate(self, request: ActionRequest, spec: PolicySpec, tool: ToolSpec | None) -> PolicyDecision:
        version = spec.version()
        digest = request.digest()

        def decide(outcome: PolicyOutcome, risk: RiskLevel, rule_id: str, reason: str) -> PolicyDecision:
            return PolicyDecision(
                step_id=request.step_id,
                outcome=outcome,
                risk=risk,
                rule_id=rule_id,
                reason=reason,
                policy_version=version,
                action_digest=digest,
            )

        if tool is None:
            return decide(
                PolicyOutcome.DENY,
                RiskLevel.HIGH,
                "unknown-tool",
                f"tool '{request.tool_name}' is not registered",
            )
        if tool.name != request.tool_name:
            return decide(
                PolicyOutcome.DENY, RiskLevel.HIGH, "tool-mismatch", "request names a different tool"
            )
        if request.policy_version != version:
            return decide(
                PolicyOutcome.DENY,
                RiskLevel.HIGH,
                "policy-version-mismatch",
                "request was built for another policy version",
            )
        if tool.side_effect == SideEffect.REAL_WRITE:
            return decide(
                PolicyOutcome.DENY,
                RiskLevel.CRITICAL,
                "real-write-denied",
                "real external writes are not permitted",
            )
        if tool.side_effect not in (SideEffect.READ, SideEffect.MOCK_WRITE):
            return decide(
                PolicyOutcome.DENY, RiskLevel.HIGH, "unknown-side-effect", "unknown side-effect class"
            )
        for rule in spec.rules:
            if rule.tool is not None and rule.tool != tool.name:
                continue
            if rule.side_effect is not None and rule.side_effect != tool.side_effect:
                continue
            if rule.outcome == PolicyOutcome.ALLOW and tool.side_effect != SideEffect.READ:
                return decide(
                    PolicyOutcome.NEEDS_APPROVAL,
                    max(rule.risk, RiskLevel.MEDIUM, key=_RISK_ORDER.index),
                    f"{rule.rule_id}+approval-forced",
                    "non-read actions always need approval (rule allowed it)",
                )
            return decide(rule.outcome, rule.risk, rule.rule_id, rule.reason)
        return decide(PolicyOutcome.DENY, RiskLevel.HIGH, "default-deny", "no rule matched")


_RISK_ORDER = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
