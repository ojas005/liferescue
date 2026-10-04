"""AuditLog (contract.interfaces.AuditLog) on SQL. Append-only BY INTERFACE (no update/delete method), BY DB (triggers +
least-privilege role, see app/db/ddl.py) and BY CONSTRUCTION (hash chain makes edits detectable).

Hash chain = PROPOSED ASSUMPTION (contract/ADR-0009). Payloads are redacted before they are hashed or stored, so the
chain covers the redacted form only; secrets never enter the table (K3)."""

from __future__ import annotations

from typing import Any

from contract.models import AuditEntryInput, AuditRecord, canonical_json, sha256_hex, utcnow
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuditRow
from app.security.keys import Redactor
from app.security.payloads import clean_payload

_PG_LOCK_KEY = 727_274_001  # arbitrary constant: serialises chain appends across processes on PostgreSQL


def chain_hash(
    prev: str, seq: int, ts_iso: str, run_id: str, actor: str, event_type: str, payload: dict[str, Any]
) -> str:
    # Same construction as contract.fakes.audit so chains from the fake and the SQL log are comparable.
    return sha256_hex(
        prev
        + canonical_json(
            {
                "seq": seq,
                "ts": ts_iso,
                "run_id": run_id,
                "actor": actor,
                "event_type": event_type,
                "payload": payload,
            }
        )
    )


def _record(r: AuditRow) -> AuditRecord:
    return AuditRecord(
        seq=r.seq,
        ts=r.ts,
        run_id=r.run_id,
        actor=r.actor,
        event_type=r.event_type,
        payload=r.payload,
        prev_hash=r.prev_hash,
        hash=r.hash,
    )


class SqlAuditLog:
    def __init__(self, session_factory: sessionmaker[Session], redactor: Redactor) -> None:
        self._sf = session_factory
        self._redactor = redactor

    async def append(self, entry: AuditEntryInput) -> AuditRecord:
        payload = clean_payload(self._redactor, entry.payload, sink="audit")
        actor = self._redactor.redact_text(entry.actor, sink="audit")
        with self._sf() as s, s.begin():
            if s.get_bind().dialect.name == "postgresql":
                s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _PG_LOCK_KEY})
            last = s.execute(select(AuditRow).order_by(AuditRow.seq.desc()).limit(1)).scalar_one_or_none()
            prev = last.hash if last else ""
            seq = (last.seq if last else 0) + 1
            ts = utcnow()
            h = chain_hash(prev, seq, ts.isoformat(), entry.run_id, actor, entry.event_type, payload)
            row = AuditRow(
                seq=seq,
                ts=ts,
                run_id=entry.run_id,
                actor=actor,
                event_type=entry.event_type,
                payload=payload,
                prev_hash=prev,
                hash=h,
            )
            s.add(row)
            s.flush()
            return _record(row)

    async def list_for_run(self, run_id: str) -> list[AuditRecord]:
        with self._sf() as s:
            rows = s.execute(
                select(AuditRow).where(AuditRow.run_id == run_id).order_by(AuditRow.seq)
            ).scalars()
            return [_record(r) for r in rows]

    async def verify_chain(self) -> bool:
        prev = ""
        with self._sf() as s:
            for r in s.execute(select(AuditRow).order_by(AuditRow.seq)).scalars():
                expected = chain_hash(
                    prev, r.seq, r.ts.isoformat(), r.run_id, r.actor, r.event_type, r.payload
                )
                if r.prev_hash != prev or r.hash != expected:
                    return False
                prev = r.hash
        return True
