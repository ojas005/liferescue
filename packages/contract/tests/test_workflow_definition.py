import pytest
from pydantic import ValidationError

from contract.fixtures.vehicle_breakdown import vehicle_breakdown
from contract.models import PolicyOutcome, RiskLevel, SideEffect
from contract.validation import InvalidInput, validate_input
from contract.workflow_definition import (
    EvidenceRequirement, PolicyRule, ResearchStrategy, ToolBinding, VerificationCheck, WorkflowDefinition,
)


def wf_dict() -> dict:
    return vehicle_breakdown().model_dump(mode="json")


def test_fixture_valid_and_roundtrips():
    wf = vehicle_breakdown()
    assert WorkflowDefinition.model_validate(wf.model_dump(mode="json")) == wf
    assert wf.workflow_id == "vehicle_breakdown"
    assert wf.tool_side_effect("web_search") == SideEffect.READ
    assert wf.tool_side_effect("nope") is None


def test_policy_version_is_stable_content_hash():
    a, b = vehicle_breakdown(), vehicle_breakdown()
    assert a.policy.version() == b.policy.version() and len(a.policy.version()) == 16
    d = wf_dict()
    d["policy"]["rules"][1]["risk"] = "low"
    assert WorkflowDefinition.model_validate(d).policy.version() != a.policy.version()


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d.update(workflow_id="Bad Id"), "workflow_id"),
    (lambda d: d.update(version="1.0"), "MAJOR.MINOR.PATCH"),
    (lambda d: d.update(unknown_field=1), "Extra inputs"),
    (lambda d: d["tools"].append({"tool": "dispatch_tow", "side_effect": "mock_write"}), "duplicate tool"),
    (lambda d: d["tools"].append({"tool": "pay", "side_effect": "real_write"}), "REAL_WRITE"),
    (lambda d: d["research"].update(tool="dispatch_tow"), "research tool must be a READ"),
    (lambda d: d["research"].update(queries=[]), "no queries"),
    (lambda d: d["policy"]["rules"].append({"rule_id": "x", "tool": "ghost", "outcome": "allow", "risk": "low", "reason": "r"}), "unknown tool"),
    (lambda d: d["policy"]["rules"].append({"rule_id": "read-ok", "side_effect": "read", "outcome": "allow", "risk": "low", "reason": "r"}), "duplicate policy rule_id"),
    (lambda d: d["policy"]["rules"].insert(0, {"rule_id": "bad", "tool": "dispatch_tow", "outcome": "allow", "risk": "low", "reason": "r"}), "requires approval"),
    (lambda d: d["policy"].update(default_outcome="allow"), "deny"),
    (lambda d: d["verification"]["checks"].append({"check_id": "z", "kind": "tool_result_status", "tool": "ghost"}), "unknown tool"),
    (lambda d: d["verification"]["checks"].append({"check_id": "z", "kind": "evidence_present", "evidence_key": "ghost"}), "unknown evidence key"),
    (lambda d: d["evidence"].append({"key": "t", "description": "d", "source": "tool", "tool": "dispatch_tow"}), "READ tool"),
    (lambda d: d["evidence"].append({"key": "description", "description": "d", "source": "user_input", "input_field": "x"}), "duplicate evidence key"),
    (lambda d: d["approvals"].update(ttl_seconds=5), "greater than or equal"),
])
def test_invalid_definitions_rejected(mutate, msg):
    d = wf_dict()
    mutate(d)
    with pytest.raises(ValidationError) as ei:
        WorkflowDefinition.model_validate(d)
    assert msg in str(ei.value)


def test_component_validators():
    with pytest.raises(ValidationError):
        EvidenceRequirement(key="k", description="d", source="user_input")
    with pytest.raises(ValidationError):
        PolicyRule(rule_id="r", outcome=PolicyOutcome.ALLOW, risk=RiskLevel.LOW, reason="x")  # matches nothing
    with pytest.raises(ValidationError):
        VerificationCheck(check_id="c", kind="model_assessment")
    with pytest.raises(ValidationError):
        ResearchStrategy(enabled=False, queries=["q"])
    with pytest.raises(ValidationError):
        ToolBinding(tool="t", side_effect="made_up")  # type: ignore[arg-type]


def test_input_validation():
    wf = vehicle_breakdown()
    validate_input(wf, {"description": "car broke down", "location": "Pune"})
    with pytest.raises(InvalidInput):
        validate_input(wf, {"location": "Pune"})
    with pytest.raises(InvalidInput):
        validate_input(wf, {"description": "ok ok", "extra": 1})
