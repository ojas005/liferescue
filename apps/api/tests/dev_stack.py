"""Dev/test composition: the contract's reference engine + fakes driven over the REAL SQL stores, policy and approvals.

This is the "develop first against the fakes" path. It lives under tests/ because arch_check R3 forbids production code
from importing contract.fakes. Dev server:  uvicorn tests.dev_app:app --port 8000
"""

from __future__ import annotations

from typing import Any

from contract.fakes import FakeToolGateway, MockModel, ReferenceRunEngine, RuleVerifier
from contract.interfaces import RunEngine
from contract.models import SideEffect, ToolSpec

from app.ports import Ports


async def _mock_ref(prefix: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"reference": f"{prefix}-0001", "simulated": True}


def fake_tools(ports: Ports) -> FakeToolGateway:
    tools = FakeToolGateway(ports.policy, ports.approvals, ports.audit)
    for name, prefix in (("report_scam", "RPT"), ("send_email", "EML"), ("create_calendar_event", "CAL")):

        async def handler(params: dict[str, Any], _p: str = prefix) -> dict[str, Any]:
            return await _mock_ref(_p, params)

        tools.register(
            ToolSpec(name=name, description=f"{name} (simulated)", side_effect=SideEffect.MOCK_WRITE), handler
        )
    return tools


def fake_engine_factory(model: MockModel | None = None) -> Any:
    def factory(ports: Ports) -> RunEngine:
        m = model or MockModel()
        tools = fake_tools(ports)
        engine = ReferenceRunEngine(
            registry=ports.registry,
            store=ports.store,
            model=m,
            tools=tools,
            policy=ports.policy,
            approvals=ports.approvals,
            audit=ports.audit,
            verifier=RuleVerifier(m),
            clock=ports.clock,
        )
        engine.tools_for_tests = tools  # type: ignore[attr-defined]
        return engine

    return factory
