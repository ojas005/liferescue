import asyncio
from datetime import timedelta

import pytest

from contract.actions import build_action_request
from contract.errors import ApprovalError, ConfigError, ConcurrentModification, ModelSchemaError, PolicyDenied, ToolError
from contract.fakes import FakeToolGateway, InMemoryApprovalService, InMemoryAuditLog, InMemoryRunStore, MockModel, RulePolicyEngine
from contract.fixtures.vehicle_breakdown import vehicle_breakdown
from contract.interfaces import (
    ApprovalService, AuditLog, ModelGateway, PolicyEngine, RunStore, ToolGateway, Verifier, assert_model_adapter_allowed, model_adapter_from_env,
)
from contract.models import (
    AssessmentResult, AuditEntryInput, PolicyOutcome, PlanProposal, SideEffect, ToolCall, ToolSpec, IntentResult, Message, EventType, RunState,
)
from contract.fakes.verifier import RuleVerifier
from contract.models import StrictModel
from contract.redaction import redact_payload

from .helpers import T0, make_run

run = asyncio.run


class Unscripted(StrictModel):
    x: int = 0
WF = vehicle_breakdown()


def stack(clock=None):
    audit, approvals, policy = InMemoryAuditLog(), InMemoryApprovalService(clock) if clock else InMemoryApprovalService(), RulePolicyEngine()
    return audit, approvals, policy, FakeToolGateway(policy, approvals, audit)


def test_fakes_satisfy_protocols():
    audit, approvals, policy, tools = stack()
    assert isinstance(audit, AuditLog) and isinstance(approvals, ApprovalService) and isinstance(policy, PolicyEngine)
    assert isinstance(tools, ToolGateway) and isinstance(MockModel(), ModelGateway) and isinstance(InMemoryRunStore(), RunStore)
    assert isinstance(RuleVerifier(), Verifier)


def test_policy_default_deny_unknown_tool_and_real_write():
    p = RulePolicyEngine()
    req = build_action_request("r", WF, "s1", "dispatch_tow", {}, "u")
    assert p.evaluate(req, WF.policy, ToolSpec(name="dispatch_tow", description="d", side_effect=SideEffect.MOCK_WRITE)).outcome == PolicyOutcome.NEEDS_APPROVAL
    assert p.evaluate(req, WF.policy, None).outcome == PolicyOutcome.DENY
    assert p.evaluate(req, WF.policy, ToolSpec(name="dispatch_tow", description="d", side_effect=SideEffect.REAL_WRITE)).rule_id == "real-write-denied"
    other = build_action_request("r", WF, "s1", "delete_everything", {}, "u")
    d = p.evaluate(other, WF.policy, ToolSpec(name="delete_everything", description="d", side_effect=SideEffect.MOCK_WRITE))
    assert d.outcome == PolicyOutcome.DENY and d.rule_id == "default-deny"  # a mock_write tool no rule mentions is denied
    d2 = p.evaluate(other, WF.policy.model_copy(update={"rules": []}), ToolSpec(name="x", description="d", side_effect=SideEffect.READ))
    assert d2.outcome == PolicyOutcome.DENY and d2.rule_id == "default-deny"


def test_read_tool_runs_without_approval_and_mock_write_is_labelled():
    audit, approvals, policy, tools = stack()
    r = run(tools.call(ToolCall(run_id="r", step_id="s", tool_name="web_search", params={"query": "tow pune"}), WF, "u"))
    assert r.status == "ok" and not r.mocked and r.output["results"]


def test_mock_write_without_approval_is_blocked_and_nothing_executes():
    audit, approvals, policy, tools = stack()
    with pytest.raises(PolicyDenied):
        run(tools.call(ToolCall(run_id="r", step_id="s", tool_name="dispatch_tow", params={"x": 1}), WF, "u"))
    assert tools.executed == []


async def _approved(approvals, policy, params):
    req = build_action_request("r", WF, "s", "dispatch_tow", params, "u")
    d = policy.evaluate(req, WF.policy, ToolSpec(name="dispatch_tow", description="d", side_effect=SideEffect.MOCK_WRITE))
    ap = await approvals.create(req, d, "tow", 900)
    return await approvals.decide(ap.approval_id, True, "u")


def test_approval_is_single_use_and_digest_bound():
    audit, approvals, policy, tools = stack()

    async def go():
        ap = await _approved(approvals, policy, {"x": 1})
        # tampered params => different digest => rejected, and the approval is NOT consumed by a failed attempt
        with pytest.raises(ApprovalError, match="different action digest"):
            await tools.call(ToolCall(run_id="r", step_id="s", tool_name="dispatch_tow", params={"x": 2}, approval_id=ap.approval_id), WF, "u")
        ok = await tools.call(ToolCall(run_id="r", step_id="s", tool_name="dispatch_tow", params={"x": 1}, approval_id=ap.approval_id), WF, "u")
        assert ok.mocked and ok.status == "ok" and ok.output["reference"].startswith("MOCK-")
        with pytest.raises(ApprovalError, match="consumed"):
            await tools.call(ToolCall(run_id="r", step_id="s", tool_name="dispatch_tow", params={"x": 1}, approval_id=ap.approval_id), WF, "u")
        assert len(tools.executed) == 1
    run(go())


def test_approval_expiry_decide_once_and_revoke():
    now = [T0]
    approvals = InMemoryApprovalService(lambda: now[0])
    policy = RulePolicyEngine()

    async def go():
        ap = await _approved(approvals, policy, {})
        with pytest.raises(ApprovalError):
            await approvals.decide(ap.approval_id, False, "u")  # already decided
        req = build_action_request("r", WF, "s2", "dispatch_tow", {}, "u")
        d = policy.evaluate(req, WF.policy, ToolSpec(name="dispatch_tow", description="d", side_effect=SideEffect.MOCK_WRITE))
        ap2 = await approvals.create(req, d, "x", 60)
        ap3 = await approvals.create(req, d, "x", 60)
        await approvals.decide(ap3.approval_id, True, "u")
        now[0] = T0 + timedelta(seconds=61)
        assert (await approvals.get(ap2.approval_id)).status.value == "expired"
        with pytest.raises(ApprovalError):
            await approvals.decide(ap2.approval_id, True, "u")
        with pytest.raises(ApprovalError):
            await approvals.consume(ap3.approval_id, req.digest())
        with pytest.raises(ApprovalError):
            await approvals.consume("nope", "d")
    run(go())


def test_gateway_rejects_unknown_tool_and_side_effect_mismatch():
    audit, approvals, policy, tools = stack()
    with pytest.raises(ToolError):
        run(tools.call(ToolCall(run_id="r", step_id="s", tool_name="rm_rf", params={}), WF, "u"))
    wrong = WF.model_copy(update={"tools": [t.model_copy(update={"side_effect": SideEffect.READ}) if t.tool == "dispatch_tow" else t for t in WF.tools]})
    with pytest.raises(PolicyDenied, match="mismatch"):
        run(tools.call(ToolCall(run_id="r", step_id="s", tool_name="dispatch_tow", params={}), wrong, "u"))


def test_audit_chain_detects_tampering_and_has_no_mutation_api():
    audit = InMemoryAuditLog()

    async def go():
        for i in range(3):
            await audit.append(AuditEntryInput(run_id="r", actor="system", event_type="e", payload={"i": i, "api_key": "sk-secret-value"}))
        assert await audit.verify_chain()
        recs = await audit.list_for_run("r")
        assert recs[0].prev_hash == "" and recs[1].prev_hash == recs[0].hash
        assert "sk-secret-value" not in recs[0].model_dump_json()  # redacted
        audit._records[1] = audit._records[1].model_copy(update={"payload": {"i": 99}})
        assert not await audit.verify_chain()
    run(go())
    assert not any(hasattr(AuditLog, n) for n in ("update", "delete", "remove", "clear"))


def test_run_store_optimistic_concurrency_and_event_seq():
    store = InMemoryRunStore()

    async def go():
        r = await store.create_run(make_run())
        e1 = await store.append_event(r.run_id, RunState.INTENT, EventType.INTENT, {})
        e2 = await store.append_event(r.run_id, RunState.INTENT, EventType.INTENT, {})
        assert (e1.seq, e2.seq) == (1, 2)
        assert [e.seq for e in await store.list_events(r.run_id, after_seq=1)] == [2]
        await store.save_run(r.model_copy(update={"version": 1}), expected_version=0)
        with pytest.raises(ConcurrentModification):
            await store.save_run(r.model_copy(update={"version": 1}), expected_version=0)
    run(go())


def test_mock_model_validates_schema_and_never_allowed_in_production():
    m = MockModel()
    res = run(m.complete_structured(IntentResult, [Message(role="user", content="hi")], purpose="intent"))
    assert isinstance(res.output, IntentResult) and res.adapter == "mock"
    with pytest.raises(ModelSchemaError):
        run(m.complete_structured(Unscripted, [], purpose="x"))
    for env in ("production", "prod", "staging"):
        with pytest.raises(ConfigError):
            assert_model_adapter_allowed(env, "mock")
    assert_model_adapter_allowed("development", "mock")
    assert_model_adapter_allowed("production", "nebius")
    with pytest.raises(ConfigError):
        assert_model_adapter_allowed("development", "openai")
    # default is nebius and mock needs an explicit non-prod env
    assert model_adapter_from_env({"LIFERESCUE_ENV": "production"}) == "nebius"
    with pytest.raises(ConfigError):
        model_adapter_from_env({"LIFERESCUE_ENV": "production", "LIFERESCUE_MODEL_ADAPTER": "mock"})
    with pytest.raises(ConfigError):
        model_adapter_from_env({"LIFERESCUE_MODEL_ADAPTER": "mock"})  # env defaults to production => fail closed
    assert model_adapter_from_env({"LIFERESCUE_ENV": "test", "LIFERESCUE_MODEL_ADAPTER": "mock"}) == "mock"


def test_redaction():
    out = redact_payload({"api_key": "abc", "nested": {"Authorization": "Bearer xyz.abc", "ok": "fine"}, "msg": "token Bearer abcdef123456 here"})
    s = str(out)
    assert "abc'" not in s and "xyz.abc" not in s and "abcdef123456" not in s and "fine" in s
