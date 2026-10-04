"""Redaction: key-based masking works today; secrets inside FREE TEXT are NOT scrubbed (QA finding F3, open question Q-S1).

Fake secrets come from tests/fixtures/redaction/fake_secrets.json (every value is clearly fake, marker 'LRQA').
Tests for the known gap are xfail(strict=True): they fail today by design and turn into XPASS (= test failure) the day
redaction improves, so the xfail marker must then be removed and the test becomes a normal regression test.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from conf_helpers import VEHICLE
from contract.fakes import MockModel
from contract.models import IntentResult, PlanProposal, PlanStepProposal, RiskLevel
from contract.redaction import MASK, redact_payload
from lr_support.fixtures_io import fake_secret_cases, load_json

F3 = "F3: contract redaction is key-based only; free-text secrets are stored/forwarded verbatim (Q-S1)"
CASES = {c["id"]: c for c in fake_secret_cases()}
MASKED = [cid for cid, c in CASES.items() if c["expected_today"] == "masked"]
NEEDLES = {cid: c["must_not_appear"] for cid, c in CASES.items()}


def gap(cid: str, **kw: Any):
    return pytest.param(cid, marks=pytest.mark.xfail(strict=True, reason=F3), id=cid, **kw)


def dumps(x: Any) -> str:
    return json.dumps(x, default=str, ensure_ascii=False)


# ------------------------------------------------------------------ fixture sanity
def test_fixture_is_clearly_fake_and_classified():
    meta = load_json("redaction/fake_secrets.json")["_meta"]
    assert meta["synthetic"] is True and meta["contains_real_personal_data"] is False
    assert sorted(CASES) == [f"RS-{n:03d}" for n in range(1, 11)]
    assert set(MASKED) == {"RS-001", "RS-002"}, MASKED
    for cid, needles in NEEDLES.items():
        for n in needles:  # every needle is either marked LRQA or one of the documented public test patterns
            assert "LRQA" in n or n in {"4111111111111111", "0000 0000 0000", "ABCDE0000F"}, (cid, n)


# ------------------------------------------------------------------ unit level: contract.redaction.redact_payload
@pytest.mark.parametrize("cid", MASKED)
def test_key_based_and_bearer_secrets_are_masked(cid):
    out = dumps(redact_payload(CASES[cid]["payload"]))
    for needle in NEEDLES[cid]:
        assert needle not in out
    assert MASK in out


@pytest.mark.parametrize(
    "cid", [gap(c) for c in ["RS-003", "RS-004", "RS-005", "RS-007", "RS-008", "RS-009", "RS-010"]]
)
def test_free_text_secrets_are_masked_by_redact_payload(cid):
    out = dumps(redact_payload(CASES[cid]["payload"]))
    for needle in NEEDLES[cid]:
        assert needle not in out, f"{cid}: {needle!r} survived redact_payload"


def test_otp_masking_policy_is_undecided():
    """RS-006: for scam_investigation the OTP phrase IS the evidence; masking policy is open question Q-S3 (LR 08 P2). No assertion possible yet."""
    assert CASES["RS-006"]["must_not_appear"] == []
    pytest.skip("Q-S3: OTP/PIN masking policy for scam_investigation is not decided")


# ------------------------------------------------------------------ system level: where does a secret typed by the user end up?
def _echo_intent_model(extra_plan: PlanProposal | None = None):
    """A model that behaves like a normal summariser: it repeats the user's words. Records every prompt it receives."""
    seen: list[str] = []

    def intent(messages):
        seen.extend(m.content for m in messages)
        desc = json.loads(messages[-1].content.split("\n", 1)[1])["description"]
        return IntentResult(
            summary="Driver reports: " + desc,
            category="breakdown",
            urgency=RiskLevel.MEDIUM,
            entities={"location": "Pune"},
        )

    resp: dict[type, Any] = {IntentResult: intent}
    if extra_plan is not None:
        resp[PlanProposal] = extra_plan
    return MockModel(resp), seen


def _run_with_secret(stack_factory, cid: str, plan: PlanProposal | None = None):
    text = CASES[cid]["payload"]["description"]
    model, prompts = _echo_intent_model(plan)
    stack = stack_factory(model=model)
    run = stack.start(VEHICLE, {"description": text, "location": "Pune"})
    return stack, run, prompts


FREE_TEXT_CASES = ["RS-003", "RS-004", "RS-005", "RS-007", "RS-010"]
SINKS = ["timeline", "run_input", "evidence", "model_prompt"]


def _sink_text(stack, run, prompts, sink: str) -> str:
    return {
        "timeline": lambda: dumps([e.payload for e in stack.events(run.run_id)]),
        "run_input": lambda: dumps(stack.get_run(run.run_id).input),
        "evidence": lambda: dumps([e.content for e in stack.evidence(run.run_id)]),
        "model_prompt": lambda: "\n".join(prompts),
    }[sink]()


SINK_PARAMS = [
    pytest.param(cid, sink, id=f"{cid}-{sink}", marks=pytest.mark.xfail(strict=True, reason=F3 + f" [{cid} -> {sink}]"))
    for cid in FREE_TEXT_CASES
    for sink in SINKS
]


@pytest.mark.parametrize("cid,sink", SINK_PARAMS)
def test_secret_in_user_free_text_does_not_reach_sink(stack_factory, cid, sink):
    stack, run, prompts = _run_with_secret(stack_factory, cid)
    text = _sink_text(stack, run, prompts, sink)
    leaked = [n for n in NEEDLES[cid] if n in text]
    assert not leaked, f"{cid}: {leaked} reached {sink}"


@pytest.mark.parametrize("cid", FREE_TEXT_CASES)
def test_audit_log_never_receives_user_free_text(stack_factory, cid):
    """Regression guard that passes today: audit payloads carry ids/digests/status only, not the user's words."""
    stack, run, _ = _run_with_secret(stack_factory, cid)
    text = dumps([r.payload for r in stack.audit(run.run_id)])
    assert not [n for n in NEEDLES[cid] if n in text]


def test_key_based_secrets_in_model_entities_are_masked_in_timeline(stack_factory):
    entities = {**CASES["RS-001"]["payload"], **CASES["RS-002"]["payload"]}
    model = MockModel({IntentResult: IntentResult(summary="s", category="breakdown", entities=entities)})
    stack = stack_factory(model=model)
    run = stack.start(VEHICLE, {"description": "car will not start", "location": "Pune"})
    out = dumps([e.payload for e in stack.events(run.run_id)]) + dumps([r.payload for r in stack.audit(run.run_id)])
    for cid in MASKED:
        for needle in NEEDLES[cid]:
            assert needle not in out


@pytest.mark.xfail(
    strict=True,
    reason=F3 + " Also finding F8: plan params and the approval summary are copied verbatim into timeline/approval.",
)
def test_secret_in_plan_params_does_not_reach_timeline_or_approval_summary(stack_factory):
    secret = CASES["RS-003"]["payload"]["description"]
    plan = PlanProposal(
        steps=[
            PlanStepProposal(
                action_type="notify_contact",
                tool_name="send_message",
                params={"to": "emergency-contact", "text": secret},
                rationale="r",
            )
        ]
    )
    stack = stack_factory(model=MockModel({PlanProposal: plan}))
    run = stack.start(VEHICLE, {"description": "car will not start", "location": "Pune"})
    needle = CASES["RS-003"]["must_not_appear"][0]
    text = dumps([e.payload for e in stack.events(run.run_id)]) + dumps(
        [a.summary for a in stack.approvals(run.run_id)]
    )
    assert needle not in text


@pytest.mark.xfail(strict=True, reason=F3 + " Validation error text echoes submitted values (finding F6).")
def test_validation_errors_do_not_echo_the_submitted_secret(stack_factory):
    from contract.validation import InvalidInput

    stack = stack_factory()
    secret = CASES["RS-003"]["payload"]["description"]
    with pytest.raises(InvalidInput) as ei:  # too long -> the validator quotes the offending value in its message
        stack.start(VEHICLE, {"description": secret + " " + "x" * 2100})
    assert CASES["RS-003"]["must_not_appear"][0] not in str(ei.value)
