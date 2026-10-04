"""RunStore (contract.interfaces.RunStore) on SQLAlchemy: PostgreSQL in the product, SQLite for default tests.
Methods are ``async`` per the port but use short synchronous transactions (acceptable at sprint scale; see README)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from contract.errors import ConcurrentModification, IllegalTransition, RunNotFound
from contract.models import EventType, Evidence, RunRecord, RunState, TimelineEvent, utcnow
from contract.run_state_machine import ALLOWED_TRANSITIONS
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.event_policy import allowlist_payload
from app.db.models import EvidenceRow, RunEventRow, RunRow
from app.security.keys import Redactor
from app.security.payloads import clean_payload


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


class SqlRunStore:
    def __init__(self, session_factory: sessionmaker[Session], redactor: Redactor) -> None:
        self._sf = session_factory
        self._redactor = redactor

    def _prepare(self, run: RunRecord) -> dict[str, Any]:
        record = run.model_dump(mode="json")
        record["input"] = clean_payload(self._redactor, record["input"])  # P2/K3: mask before storage
        return record

    async def create_run(self, run: RunRecord) -> RunRecord:
        rid = _uuid(run.run_id)
        if rid is None:
            raise ValueError("run_id must be a UUID")
        record = self._prepare(run)
        with self._sf() as s, s.begin():
            s.add(
                RunRow(
                    id=rid,
                    workflow_id=run.workflow_id,
                    workflow_version=run.workflow_version,
                    contract_version=run.contract_version,
                    owner=run.owner,
                    state=run.state.value,
                    version=run.version,
                    record=record,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                )
            )
        return RunRecord.model_validate(record)

    async def get_run(self, run_id: str) -> RunRecord | None:
        rid = _uuid(run_id)
        if rid is None:
            return None
        with self._sf() as s:
            row = s.get(RunRow, rid)
            return RunRecord.model_validate(row.record) if row else None

    async def save_run(self, run: RunRecord, expected_version: int) -> RunRecord:
        rid = _uuid(run.run_id)
        if rid is None:
            raise RunNotFound(run.run_id)
        record = self._prepare(run)
        with self._sf() as s, s.begin():
            row = s.execute(select(RunRow).where(RunRow.id == rid).with_for_update()).scalar_one_or_none()
            if row is None:
                raise RunNotFound(run.run_id)
            if row.version != expected_version:
                raise ConcurrentModification(f"stored version {row.version} != expected {expected_version}")
            old, new = RunState(row.state), run.state
            # Defence in depth: the store refuses any state change apply_transition would not allow.
            if new != old and new not in ALLOWED_TRANSITIONS[old]:
                raise IllegalTransition(f"{old.value} -> {new.value} is not allowed")
            if new == old and old in (
                RunState.COMPLETED,
                RunState.FAILED,
                RunState.DENIED,
                RunState.CANCELLED,
            ):
                raise IllegalTransition(f"run is terminal ({old.value})")
            res = s.execute(
                update(RunRow)
                .where(RunRow.id == rid, RunRow.version == expected_version)
                .values(state=new.value, version=run.version, record=record, updated_at=run.updated_at)
            )
            if res.rowcount != 1:  # type: ignore[attr-defined]
                raise ConcurrentModification("run changed concurrently")
        return RunRecord.model_validate(record)

    async def append_event(
        self,
        run_id: str,
        step: RunState,
        type: EventType,
        payload: dict[str, Any],
        ts: datetime | None = None,
    ) -> TimelineEvent:
        rid = _uuid(run_id)
        if rid is None:
            raise RunNotFound(run_id)
        safe = clean_payload(self._redactor, allowlist_payload(type, payload))
        with self._sf() as s, s.begin():
            if (
                s.execute(select(RunRow.id).where(RunRow.id == rid).with_for_update()).scalar_one_or_none()
                is None
            ):
                raise RunNotFound(
                    run_id
                )  # the row lock above serialises seq assignment per run on PostgreSQL
            last = s.execute(
                select(func.coalesce(func.max(RunEventRow.seq), 0)).where(RunEventRow.run_id == rid)
            ).scalar_one()
            row = RunEventRow(
                id=uuid.uuid4(),
                run_id=rid,
                seq=int(last) + 1,
                ts=ts or utcnow(),
                step=step.value,
                type=type.value,
                payload=safe,
            )
            s.add(row)
            s.flush()
            return _event(row)

    async def list_events(self, run_id: str, after_seq: int = 0, limit: int = 200) -> list[TimelineEvent]:
        rid = _uuid(run_id)
        if rid is None:
            raise RunNotFound(run_id)
        limit = max(1, min(limit, 500))
        with self._sf() as s:
            if s.get(RunRow, rid) is None:
                raise RunNotFound(run_id)
            rows = s.execute(
                select(RunEventRow)
                .where(RunEventRow.run_id == rid, RunEventRow.seq > after_seq)
                .order_by(RunEventRow.seq)
                .limit(limit)
            ).scalars()
            return [_event(r) for r in rows]

    async def add_evidence(self, evidence: Evidence) -> None:
        rid = _uuid(evidence.run_id)
        if rid is None:
            raise RunNotFound(evidence.run_id)
        content = clean_payload(self._redactor, evidence.content)
        with self._sf() as s, s.begin():
            if s.get(RunRow, rid) is None:
                raise RunNotFound(evidence.run_id)
            s.add(
                EvidenceRow(
                    id=_uuid(evidence.evidence_id) or uuid.uuid4(),
                    run_id=rid,
                    key=evidence.key,
                    kind=evidence.kind,
                    source=evidence.source,
                    content=content,
                    trust=evidence.trust,
                    retrieved_at=evidence.retrieved_at,
                    sha256=evidence.sha256,
                )
            )

    async def list_evidence(self, run_id: str) -> list[Evidence]:
        rid = _uuid(run_id)
        if rid is None:
            raise RunNotFound(run_id)
        with self._sf() as s:
            rows = s.execute(
                select(EvidenceRow).where(EvidenceRow.run_id == rid).order_by(EvidenceRow.retrieved_at)
            ).scalars()
            return [
                Evidence(
                    evidence_id=str(r.id),
                    run_id=str(r.run_id),
                    key=r.key,
                    kind=r.kind,
                    source=r.source,
                    content=r.content,
                    trust=r.trust,
                    retrieved_at=r.retrieved_at,
                    sha256=r.sha256,
                )
                for r in rows
            ]


def _event(r: RunEventRow) -> TimelineEvent:
    return TimelineEvent(
        event_id=str(r.id),
        run_id=str(r.run_id),
        seq=r.seq,
        ts=r.ts,
        step=RunState(r.step),
        type=EventType(r.type),
        payload=r.payload,
    )
