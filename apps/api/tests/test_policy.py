"""PolicyEngine: deny by default, fail closed, mock_write always needs approval (T1, T3, T4)."""

from typing import Any

import pytest
from contract.models import ActionRequest, PolicyOutcome, RiskLevel, SideEffect, ToolSpec
from contract.workflow_definition import PolicyRule, PolicySpec

from app.policy.engine import DeterministicPolicyEngine

E = DeterministicPolicyEngine()
READ = ToolSpec(name="web_search", description="d", side_effect=SideEffect.READ)
WRITE = ToolSpec(name="dispatch_tow", description="d", side_effect=SideEffect.MOCK_WRITE)
REAL = ToolSpec(name="wire_money", description="d", side_effect=SideEffect.REAL_WRITE)


def spec(*rules: PolicyRule) -> PolicySpec:
    return PolicySpec(rules=list(rules))


RULES = spec(
    PolicyRule(
        rule_id="read-ok",
        side_effect=SideEffect.READ,
        outcome=PolicyOutcome.ALLOW,
        risk=RiskLevel.LOW,
        reason="r",
    ),
    PolicyRule(
        rule_id="tow",
        tool="dispatch_tow",
        outcome=PolicyOutcome.NEEDS_APPROVAL,
        risk=RiskLevel.HIGH,
        reason="r",
    ),
)


def req(tool: str, s: PolicySpec = RULES, **kw: Any) -> ActionRequest:
    base: dict[str, Any] = dict(
        run_id="r1",
        workflow_id="wf_test",
        workflow_version="0.1.0",
        step_id="s1",
        tool_name=tool,
        params={"a": 1},
        policy_version=s.version(),
        requested_by="demo-user",
    )
    base.update(kw)
    return ActionRequest(**base)


@pytest.mark.parametrize(
    ("tool", "spec_", "request_kw", "outcome", "rule"),
    [
        (READ, RULES, {}, PolicyOutcome.ALLOW, "read-ok"),
        (WRITE, RULES, {}, PolicyOutcome.NEEDS_APPROVAL, "tow"),
        (None, RULES, {}, PolicyOutcome.DENY, "unknown-tool"),  # unknown tool
        (REAL, RULES, {}, PolicyOutcome.DENY, "real-write-denied"),  # REAL_WRITE never
        (
            ToolSpec(name="web_search", description="d", side_effect=SideEffect.READ),
            spec(),
            {},
            PolicyOutcome.DENY,
            "default-deny",
        ),
        (READ, RULES, {"tool_name": "dispatch_tow"}, PolicyOutcome.DENY, "tool-mismatch"),
        (READ, RULES, {"policy_version": "stale"}, PolicyOutcome.DENY, "policy-version-mismatch"),
    ],
)
def test_decisions(
    tool: ToolSpec | None, spec_: PolicySpec, request_kw: dict[str, Any], outcome: PolicyOutcome, rule: str
) -> None:
    name = request_kw.get("tool_name") or (tool.name if tool else "ghost_tool")
    d = E.evaluate(req(name, spec_, **{k: v for k, v in request_kw.items() if k != "tool_name"}), spec_, tool)
    assert (d.outcome, d.rule_id) == (outcome, rule)
    assert d.policy_version == spec_.version() and d.reason


def test_rule_allowing_mock_write_is_upgraded_to_approval() -> None:
    lax = spec(
        PolicyRule(
            rule_id="lax",
            side_effect=SideEffect.MOCK_WRITE,
            outcome=PolicyOutcome.ALLOW,
            risk=RiskLevel.LOW,
            reason="r",
        )
    )
    d = E.evaluate(req("dispatch_tow", lax), lax, WRITE)
    assert (
        d.outcome == PolicyOutcome.NEEDS_APPROVAL
        and d.rule_id == "lax+approval-forced"
        and d.risk == RiskLevel.MEDIUM
    )


def test_first_match_wins_and_deny_rule_is_honoured() -> None:
    s = spec(
        PolicyRule(
            rule_id="deny-tow",
            tool="dispatch_tow",
            outcome=PolicyOutcome.DENY,
            risk=RiskLevel.CRITICAL,
            reason="no",
        ),
        PolicyRule(
            rule_id="late",
            tool="dispatch_tow",
            outcome=PolicyOutcome.NEEDS_APPROVAL,
            risk=RiskLevel.LOW,
            reason="r",
        ),
    )
    assert E.evaluate(req("dispatch_tow", s), s, WRITE).rule_id == "deny-tow"


def test_decision_binds_exact_inputs_digest() -> None:
    a, b = req("web_search"), req("web_search", params={"a": 2})
    da, db = E.evaluate(a, RULES, READ), E.evaluate(b, RULES, READ)
    assert da.action_digest == a.digest() != db.action_digest == b.digest()


def test_exception_fails_closed_without_leaking() -> None:
    class Boom:
        def version(self) -> str:
            raise RuntimeError("secret-internal-detail")

    d = E.evaluate(req("web_search"), Boom(), READ)  # type: ignore[arg-type]
    assert (
        d.outcome == PolicyOutcome.DENY
        and d.rule_id == "policy-error"
        and "secret-internal-detail" not in d.reason
    )


def test_policy_version_is_content_hash() -> None:
    assert E.policy_version(RULES) == RULES.version()
    other = spec(
        PolicyRule(
            rule_id="x",
            side_effect=SideEffect.READ,
            outcome=PolicyOutcome.ALLOW,
            risk=RiskLevel.LOW,
            reason="r",
        )
    )
    assert E.policy_version(other) != E.policy_version(RULES)
