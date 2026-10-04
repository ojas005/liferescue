"""In-memory RunStore and WorkflowRegistry (tests and parallel development only)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ..errors import ConcurrentModification, RunNotFound
from ..models import EventType, Evidence, RunRecord, RunState, TimelineEvent, utcnow
from ..workflow_definition import WorkflowDefinition


class InMemoryWorkflowRegistry:
    def __init__(self, definitions: list[WorkflowDefinition]) -> None:
        self._defs = {(d.workflow_id, d.version): d for d in definitions}

    def list(self) -> list[WorkflowDefinition]:
        return list(self._defs.values())

    def get(self, workflow_id: str, version: str | None = None) -> WorkflowDefinition | None:
        if version is not None:
            return self._defs.get((workflow_id, version))
        cands = [d for (wid, _), d in self._defs.items() if wid == workflow_id]
        return sorted(cands, key=lambda d: tuple(int(x) for x in d.version.split(".")))[-1] if cands else None


class InMemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._events: dict[str, list[TimelineEvent]] = {}
        self._evidence: dict[str, list[Evidence]] = {}

    async def create_run(self, run: RunRecord) -> RunRecord:
        self._runs[run.run_id] = run
        self._events[run.run_id] = []
        self._evidence[run.run_id] = []
        return run

    async def get_run(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    async def save_run(self, run: RunRecord, expected_version: int) -> RunRecord:
        cur = self._runs.get(run.run_id)
        if cur is None:
            raise RunNotFound(run.run_id)
        if cur.version != expected_version:
            raise ConcurrentModification(f"stored version {cur.version} != expected {expected_version}")
        self._runs[run.run_id] = run
        return run

    async def append_event(self, run_id: str, step: RunState, type: EventType, payload: dict[str, Any],
                           ts: datetime | None = None) -> TimelineEvent:
        if run_id not in self._events:
            raise RunNotFound(run_id)
        seq = len(self._events[run_id]) + 1
        ev = TimelineEvent(event_id=str(uuid.uuid4()), run_id=run_id, seq=seq, ts=ts or utcnow(), step=step, type=type, payload=payload)
        self._events[run_id].append(ev)
        return ev

    async def list_events(self, run_id: str, after_seq: int = 0, limit: int = 200) -> list[TimelineEvent]:
        if run_id not in self._events:
            raise RunNotFound(run_id)
        return [e for e in self._events[run_id] if e.seq > after_seq][:limit]

    async def add_evidence(self, evidence: Evidence) -> None:
        self._evidence.setdefault(evidence.run_id, []).append(evidence)

    async def list_evidence(self, run_id: str) -> list[Evidence]:
        return list(self._evidence.get(run_id, []))
