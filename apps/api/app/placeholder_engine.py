"""Minimal RunEngine used ONLY while the real runtime (app/runtime/wiring.py, LR 06) is not wired.

It validates input, creates the run at INTENT and records the first timeline/audit entries, then STOPS: it never
advances stages (no second orchestrator). Cancel and approval decisions are supported at the persistence level so the API
contract is fully exercisable. Replace by providing ``app.runtime.wiring.build_engine``."""

from __future__ import annotations

import uuid
from typing import Any

from contract import CONTRACT_VERSION
from contract.errors import ApprovalError, RunNotFound, WorkflowNotFound
from contract.models import AuditEntryInput, EventType, RunRecord, RunState
from contract.run_state_machine import TransitionContext, apply_transition
from contract.validation import validate_input

from app.ports import Ports


class PlaceholderRunEngine:
    def __init__(self, ports: Ports) -> None:
        self.p = ports

    async def start(
        self, workflow_id: str, input: dict[str, Any], workflow_version: str | None = None
    ) -> RunRecord:
        wf = self.p.registry.get(workflow_id, workflow_version)
        if wf is None:
            raise WorkflowNotFound(workflow_id)
        validate_input(wf, input)
        now = self.p.clock()
        run = await self.p.store.create_run(
            RunRecord(
                run_id=str(uuid.uuid4()),
                workflow_id=wf.workflow_id,
                workflow_version=wf.version,
                contract_version=CONTRACT_VERSION,
                input=input,
                created_at=now,
                updated_at=now,
            )
        )
        await self.p.audit.append(
            AuditEntryInput(
                run_id=run.run_id,
                actor="system",
                event_type="run_created",
                payload={"workflow_id": wf.workflow_id, "workflow_version": wf.version},
            )
        )
        await self.p.store.append_event(
            run.run_id,
            RunState.INTENT,
            EventType.STATE_CHANGE,
            {"to": "intent", "note": "run created (runtime not wired)"},
        )
        return run

    async def advance(self, run_id: str) -> RunRecord:
        run = await self.p.store.get_run(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return run

    async def decide_approval(
        self, run_id: str, approval_id: str, approve: bool, decided_by: str, reason: str | None = None
    ) -> RunRecord:
        raise ApprovalError("no runtime is wired; approvals cannot be decided")

    async def cancel(self, run_id: str, requested_by: str, reason: str | None = None) -> RunRecord:
        run = await self.advance(run_id)
        new = apply_transition(
            run,
            RunState.CANCELLED,
            TransitionContext(reason=reason or "cancelled by user", now=self.p.clock()),
        )
        await self.p.approvals.revoke_pending(run_id)
        saved = await self.p.store.save_run(new, expected_version=run.version)
        await self.p.store.append_event(
            run_id,
            saved.state,
            EventType.STATE_CHANGE,
            {"from": run.state.value, "to": saved.state.value, "reason": saved.terminal_reason},
        )
        await self.p.audit.append(
            AuditEntryInput(
                run_id=run_id,
                actor=f"user:{requested_by}",
                event_type="state_change",
                payload={"from": run.state.value, "to": saved.state.value, "reason": saved.terminal_reason},
            )
        )
        return saved
