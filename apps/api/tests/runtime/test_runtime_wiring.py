"""build_engine / Ports: the drop-in for LR 04's composition root (KAN-39)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from contract import errors as ce
from contract.fakes import (
    FakeResearchProvider,
    InMemoryApprovalService,
    InMemoryAuditLog,
    InMemoryRunStore,
    InMemoryWorkflowRegistry,
    RulePolicyEngine,
)
from contract.interfaces import RunEngine, ToolSpec
from contract.models import ApprovalStatus, RunState, SideEffect, utcnow
from demo_support import NotifyParams, demo_definition, run_async

from app.runtime import WorkflowEngine
from app.runtime.mock_tools import discover_mock_tools
from app.runtime.model_gateway import MockAIProvider, NebiusProvider
from app.runtime.tools import strict_schema
from app.runtime.wiring import Ports, build_engine

NOTIFY = ToolSpec(
    name="demo_notify",
    description="Send a simulated notification",
    side_effect=SideEffect.MOCK_WRITE,
    input_schema=strict_schema(NotifyParams),
)


def make_ports(**kw):
    approvals = InMemoryApprovalService(utcnow)
    base = {
        "registry": InMemoryWorkflowRegistry([demo_definition()]),
        "run_store": InMemoryRunStore(),
        "audit_log": InMemoryAuditLog(),
        "approval_service": approvals,
        "policy_engine": RulePolicyEngine(),
        "model_gateway": MockAIProvider(workflow=demo_definition()),
        "research_provider": FakeResearchProvider(),
        "mock_tools": [NOTIFY],
    }
    base.update(kw)
    return Ports(**base)


async def pending(ports, run_id):
    return [
        a
        for a in await ports.approval_service.list_for_run(run_id)
        if a.status == ApprovalStatus.PENDING
    ]


def test_build_engine_returns_a_run_engine_and_runs_to_approval_then_completion():
    ports = make_ports()
    engine = build_engine(ports)
    assert isinstance(engine, WorkflowEngine)
    assert isinstance(engine, RunEngine)

    async def go():
        run = await engine.start("demo_notify", {"message": "my car broke down"})
        assert run.state == RunState.APPROVAL
        (ap,) = await pending(ports, run.run_id)
        return await engine.decide_approval(run.run_id, ap.approval_id, True, "demo-user")

    assert run_async(go()).state == RunState.COMPLETED


def test_lr04_style_ports_object_is_accepted_duck_typed():
    p = make_ports()
    lr04 = SimpleNamespace(
        settings=SimpleNamespace(model_adapter="mock", liferescue_env="development"),
        registry=p.registry,
        store=p.run_store,
        audit=p.audit_log,
        approvals=p.approval_service,
        policy=p.policy_engine,
        redactor=object(),
        clock=utcnow,
        mock_tools=[NOTIFY],
        research_provider=FakeResearchProvider(),
    )
    engine = build_engine(lr04)
    assert isinstance(engine, WorkflowEngine)
    assert isinstance(engine.provider, MockAIProvider)
    run = run_async(engine.start("demo_notify", {"message": "hello there"}))
    assert run.state == RunState.APPROVAL


def test_mock_provider_is_refused_in_production_via_lr04_settings():
    p = make_ports()
    lr04 = SimpleNamespace(
        settings=SimpleNamespace(model_adapter="mock", liferescue_env="production"),
        registry=p.registry,
        store=p.run_store,
        audit=p.audit_log,
        approvals=p.approval_service,
        policy=p.policy_engine,
        clock=utcnow,
        mock_tools=[NOTIFY],
    )
    with pytest.raises(ce.ConfigError):
        build_engine(lr04)


def test_default_provider_is_nebius_and_never_fails_at_build_without_a_key():
    p = make_ports(model_gateway=None, env={})
    engine = build_engine(p)
    assert isinstance(engine.provider, NebiusProvider)
    assert not engine.provider.is_configured()


def test_unregistered_mock_write_tool_fails_at_startup_not_at_run_time():
    with pytest.raises(ce.ConfigError):
        build_engine(make_ports(mock_tools=[]))


def test_auto_advance_false_start_only_creates_then_advance_is_resumable_and_idempotent():
    ports = make_ports(auto_advance=False)
    engine = build_engine(ports)

    async def go():
        run = await engine.start("demo_notify", {"message": "my car broke down"})
        assert run.state == RunState.INTENT
        a = await engine.advance(run.run_id)
        assert a.state == RunState.APPROVAL
        n_events = len(await ports.run_store.list_events(run.run_id))
        b = await engine.advance(run.run_id)  # blocked on approval: no-op
        assert b.state == RunState.APPROVAL
        assert len(await ports.run_store.list_events(run.run_id)) == n_events
        return run.run_id

    run_async(go())


def test_concurrent_advance_calls_on_one_run_do_not_double_execute():
    ports = make_ports(auto_advance=False)
    engine = build_engine(ports)

    async def go():
        run = await engine.start("demo_notify", {"message": "my car broke down"})
        results = await asyncio.gather(*[engine.advance(run.run_id) for _ in range(5)])
        assert {r.state for r in results} == {RunState.APPROVAL}
        evs = await ports.run_store.list_events(run.run_id)
        seqs = [e.seq for e in evs]
        assert seqs == sorted(set(seqs))  # gap-free, no duplicates
        assert len(await pending(ports, run.run_id)) == 1  # exactly one live approval

    run_async(go())


def test_discover_mock_tools_is_generic_and_returns_unique_names():
    names = [t.name for t in discover_mock_tools()]
    assert len(names) == len(set(names))
