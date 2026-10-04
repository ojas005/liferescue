"""Stack adapter: the SAME conformance tests run against the contract fakes now and the real stack later.

Select with env LR_STACK=fake|real (default fake). `real` is not wired yet: the fixture skips with a reason.
All methods are synchronous wrappers (asyncio.run) over the contract Protocols, so tests read top to bottom.

What a test may use on every stack (contract surface): start, get_run, approvals, decide, cancel, advance, events,
audit, evidence, audit_chain_ok, call_tool, executed_tools (derived from AUDIT records, not from fake internals).
Fake-only helpers (`supports_*` flags) let a test skip itself on a stack that cannot do the thing (clock control,
direct store tampering, replacing a tool handler, registering an extra tool).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import pytest

from contract.interfaces import ModelGateway
from contract.models import (
    Approval,
    AuditRecord,
    Evidence,
    RunRecord,
    TimelineEvent,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from contract.workflow_definition import WorkflowDefinition

T = TypeVar("T")
STACK_KINDS = ("fake", "real")
T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
REAL_SKIP_REASON = (
    "LR_STACK=real: the real stack adapter is not wired yet (waits for the LR 06 runtime and LR 04 composition root); "
    "these conformance tests are written against contract Protocols so they can run unchanged once it is."
)


def selected_kind() -> str:
    kind = os.environ.get("LR_STACK", "fake").strip().lower() or "fake"
    if kind not in STACK_KINDS:
        raise pytest.UsageError(f"LR_STACK must be one of {STACK_KINDS}, got {kind!r}")
    return kind


class ManualClock:
    """Deterministic clock; `advance(seconds)` moves time forward (used for approval expiry)."""

    def __init__(self, start: datetime = T0) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


@dataclass(frozen=True)
class Executed:
    """One tool execution as recorded by the AUDIT log (event_type == 'tool_executed')."""

    tool: str
    step_id: str
    status: str
    mocked: bool
    digest: str


class FakeStack:
    kind = "fake"
    supports_clock = True
    supports_store_tamper = True
    supports_tool_override = True
    supports_extra_tools = True

    def __init__(
        self,
        definitions: Sequence[WorkflowDefinition] | None = None,
        model: ModelGateway | None = None,
        extra_tools: Sequence[tuple[ToolSpec, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]] = (),
    ) -> None:
        from contract.fakes import (
            FakeToolGateway,
            InMemoryApprovalService,
            InMemoryAuditLog,
            InMemoryRunStore,
            InMemoryWorkflowRegistry,
            MockModel,
            ReferenceRunEngine,
            RulePolicyEngine,
            RuleVerifier,
        )
        from contract.fixtures.vehicle_breakdown import vehicle_breakdown

        # Same wiring as contract.fakes.build_fake_stack(), spelled out so extra tools can be registered BEFORE the engine
        # validates the workflows against the tool registry (build_fake_stack() has no hook for that).
        self.clock = ManualClock()
        self.definitions = list(definitions) if definitions is not None else [vehicle_breakdown()]
        audit, approvals, policy = InMemoryAuditLog(), InMemoryApprovalService(self.clock), RulePolicyEngine()
        tools = FakeToolGateway(policy, approvals, audit)
        for spec, handler in extra_tools:
            tools.register(spec, handler)
        m = model or MockModel()
        self.engine = ReferenceRunEngine(
            registry=InMemoryWorkflowRegistry(self.definitions),
            store=InMemoryRunStore(),
            model=m,
            tools=tools,
            policy=policy,
            approvals=approvals,
            audit=audit,
            verifier=RuleVerifier(m),
            clock=self.clock,
        )
        self.model = m

    # -- helpers
    def _run(self, coro: Awaitable[T]) -> T:
        return asyncio.run(coro)  # type: ignore[arg-type]

    def workflow(self, workflow_id: str) -> WorkflowDefinition:
        wf = self.engine.registry.get(workflow_id)
        assert wf is not None, workflow_id
        return wf

    # -- RunEngine surface
    def start(self, workflow_id: str, input: dict[str, Any]) -> RunRecord:
        return self._run(self.engine.start(workflow_id, input))

    def advance(self, run_id: str) -> RunRecord:
        return self._run(self.engine.advance(run_id))

    def get_run(self, run_id: str) -> RunRecord:
        run = self._run(self.engine.store.get_run(run_id))
        assert run is not None
        return run

    def decide(self, run_id: str, approval_id: str, approve: bool, reason: str | None = None) -> RunRecord:
        return self._run(self.engine.decide_approval(run_id, approval_id, approve, "demo-user", reason))

    def cancel(self, run_id: str, reason: str | None = None) -> RunRecord:
        return self._run(self.engine.cancel(run_id, "demo-user", reason))

    # -- read side
    def approvals(self, run_id: str) -> list[Approval]:
        return self._run(self.engine.approvals.list_for_run(run_id))

    def events(self, run_id: str) -> list[TimelineEvent]:
        return self._run(self.engine.store.list_events(run_id, 0, 10_000))

    def audit(self, run_id: str) -> list[AuditRecord]:
        return self._run(self.engine.audit.list_for_run(run_id))

    def evidence(self, run_id: str) -> list[Evidence]:
        return self._run(self.engine.store.list_evidence(run_id))

    def audit_chain_ok(self) -> bool:
        return self._run(self.engine.audit.verify_chain())

    def executed_tools(self, run_id: str) -> list[Executed]:
        out = []
        for r in self.audit(run_id):
            if r.event_type == "tool_executed":
                p = r.payload
                out.append(
                    Executed(
                        tool=r.actor.removeprefix("tool:"),
                        step_id=p["step_id"],
                        status=p["status"],
                        mocked=bool(p["mocked"]),
                        digest=p["digest"],
                    )
                )
        return out

    def executed_mock_writes(self, run_id: str) -> list[Executed]:
        return [e for e in self.executed_tools(run_id) if e.mocked]

    def call_tool(self, call: ToolCall, workflow_id: str = "vehicle_breakdown") -> ToolResult:
        """Call the ToolGateway directly (the single execution path). Raises the contract errors."""
        return self._run(self.engine.tools.call(call, self.workflow(workflow_id), "demo-user"))

    # -- fake-only helpers (guarded by supports_* flags)
    def tamper_plan_params(self, run_id: str, step_index: int, params: dict[str, Any]) -> None:
        """Rewrite stored plan params AFTER approval (simulates a DB/store tamper). Fake only."""
        run = self.get_run(run_id)
        plan = list(run.plan)
        plan[step_index] = plan[step_index].model_copy(update={"params": params})
        self._run(self.engine.store.save_run(run.model_copy(update={"plan": plan}), expected_version=run.version))

    def override_tool(self, spec: ToolSpec, handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        self.engine.tools.register(spec, handler)  # type: ignore[attr-defined]


class RealStack:
    """Placeholder. Wire to the real runtime (LR 06) + API (LR 04) when they exist; keep the FakeStack method names."""

    kind = "real"

    def __init__(self, *a: Any, **k: Any) -> None:
        pytest.skip(REAL_SKIP_REASON)


def make_stack_factory(kind: str) -> Callable[..., FakeStack]:
    if kind == "fake":
        return FakeStack
    if kind == "real":
        return RealStack  # type: ignore[return-value]
    raise pytest.UsageError(f"unknown stack kind {kind!r}")
