"""Fixtures validation: tests/fixtures is well formed, synthetic, contract-valid, and actually drives the stack."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from conf_helpers import VEHICLE, S
from contract.fakes import MockModel
from contract.models import AssessmentResult, IntentResult, PlanProposal
from lr_support.fixtures_io import FIXTURES, golden_cases, load_json


def _validator_module():
    spec = importlib.util.spec_from_file_location("validate_fixtures", FIXTURES / "validate_fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_validate_fixtures_script_is_clean(capsys):
    mod = _validator_module()
    assert mod.main() == 0, capsys.readouterr().out
    last = mod.LAST
    assert last["errors"] == [] and last["warns"] == []
    assert last["contract_loaded"] is True, "contract types must be importable so model fixtures are really validated"
    assert last["contract_objects"] >= 27


def test_fixture_inventory():
    def names(sub):
        return sorted(p.name for p in (FIXTURES / sub).glob("*.json"))

    assert (
        len(names("tavily")) == 8
        and len(names("mock_model")) == 6
        and len(names("golden")) == 4
        and names("redaction") == ["fake_secrets.json"]
    )
    assert sum(len(golden_cases(n)) for n in names("golden")) == 19


@pytest.mark.parametrize("path", sorted(FIXTURES.rglob("*.json")), ids=lambda p: str(p.relative_to(FIXTURES)))
def test_every_fixture_is_labelled_synthetic(path: Path):
    meta = load_json(str(path.relative_to(FIXTURES)))["_meta"]
    assert meta["synthetic"] is True and meta["contains_real_personal_data"] is False
    assert "pending frozen" not in meta.get("schema_status", "").lower()


def test_vehicle_golden_inputs_satisfy_the_contract_input_schema():
    from contract.fixtures.vehicle_breakdown import vehicle_breakdown

    schema = vehicle_breakdown().intent.input_schema
    for c in golden_cases("vehicle_breakdown_cases.json"):
        assert not list(Draft202012Validator(schema).iter_errors(c["api_input"])), c["id"]


def _model_from(fixture: str, variant: str | None = None) -> MockModel:
    d = load_json(f"mock_model/{fixture}.json")
    outs = {
        **d["outputs"],
        **({k: v for k, v in d["variants"][variant].items() if not k.startswith("_")} if variant else {}),
    }
    return MockModel(
        {
            IntentResult: IntentResult(**outs["IntentResult"]),
            PlanProposal: PlanProposal(**outs["PlanProposal"]),
            AssessmentResult: AssessmentResult(**outs["AssessmentResult"]),
        }
    )


@pytest.mark.parametrize("case", golden_cases("vehicle_breakdown_cases.json"), ids=lambda c: c["id"])
def test_vehicle_golden_input_reaches_approval_with_the_canned_model(stack_factory, case):
    """Golden input + the matching canned model outputs run through the stack and stop at approval (the canned plan is mock_write)."""
    d = load_json("mock_model/vehicle_breakdown.json")
    stack = stack_factory(model=_model_from("vehicle_breakdown"))
    run = stack.start(VEHICLE, case["api_input"])
    if case["id"] == d["_meta"]["golden_case"]:
        assert run.state == S.APPROVAL, (run.state, run.terminal_reason)
        assert stack.executed_mock_writes(run.run_id) == []
    else:
        # canned outputs belong to one golden case; the others only need to start cleanly and never write without approval
        assert run.state in (S.APPROVAL, S.COMPLETED, S.FAILED)
        assert stack.executed_mock_writes(run.run_id) == []


@pytest.mark.parametrize(
    "variant,final",
    [
        ("unlisted_tool_plan", S.FAILED),
        ("disallowed_action_type_plan", S.FAILED),
        ("too_many_steps_plan", S.FAILED),
        ("read_only_plan", S.COMPLETED),
    ],
)
def test_vehicle_model_variants_behave_as_their_expect_note_says(stack_factory, variant, final):
    d = load_json("mock_model/vehicle_breakdown.json")
    case = next(c for c in golden_cases("vehicle_breakdown_cases.json") if c["id"] == d["_meta"]["golden_case"])
    stack = stack_factory(model=_model_from("vehicle_breakdown", variant))
    run = stack.start(VEHICLE, case["api_input"])
    assert run.state == final, (variant, run.state, run.terminal_reason, d["variants"][variant]["_expect"])
    assert stack.executed_mock_writes(run.run_id) == [] or final == S.COMPLETED
    if variant == "read_only_plan":
        assert stack.approvals(run.run_id) == []
