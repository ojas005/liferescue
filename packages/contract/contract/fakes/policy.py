"""RulePolicyEngine: reference deterministic policy (first match wins, default DENY). No LLM, no I/O."""
from __future__ import annotations

from ..models import ActionRequest, PolicyDecision, PolicyOutcome, RiskLevel, SideEffect, ToolSpec
from ..workflow_definition import PolicySpec


class RulePolicyEngine:
    def policy_version(self, spec: PolicySpec) -> str:
        return spec.version()

    def evaluate(self, request: ActionRequest, spec: PolicySpec, tool: ToolSpec | None) -> PolicyDecision:
        version = spec.version()
        digest = request.digest()

        def decision(outcome: PolicyOutcome, risk: RiskLevel, rule_id: str, reason: str) -> PolicyDecision:
            return PolicyDecision(step_id=request.step_id, outcome=outcome, risk=risk, rule_id=rule_id, reason=reason,
                                  policy_version=version, action_digest=digest)

        if tool is None:
            return decision(PolicyOutcome.DENY, RiskLevel.HIGH, "unknown-tool", f"tool '{request.tool_name}' is not registered")
        if tool.side_effect == SideEffect.REAL_WRITE:
            return decision(PolicyOutcome.DENY, RiskLevel.CRITICAL, "real-write-denied", "real external writes are not permitted")
        for rule in spec.rules:
            if rule.tool is not None and rule.tool != tool.name:
                continue
            if rule.side_effect is not None and rule.side_effect != tool.side_effect:
                continue
            return decision(rule.outcome, rule.risk, rule.rule_id, rule.reason)
        return decision(PolicyOutcome.DENY, RiskLevel.HIGH, "default-deny", "no rule matched")
