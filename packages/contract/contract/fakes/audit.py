"""In-memory append-only AuditLog with a SHA-256 hash chain (chain is an ASSUMPTION). No update/delete API exists."""
from __future__ import annotations

from ..models import AuditEntryInput, AuditRecord, canonical_json, sha256_hex, utcnow
from ..redaction import redact_payload


def _hash(prev: str, seq: int, ts: str, entry: AuditEntryInput, payload: dict) -> str:  # type: ignore[type-arg]
    return sha256_hex(prev + canonical_json({"seq": seq, "ts": ts, "run_id": entry.run_id, "actor": entry.actor,
                                             "event_type": entry.event_type, "payload": payload}))


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    async def append(self, entry: AuditEntryInput) -> AuditRecord:
        payload = redact_payload(entry.payload)
        prev = self._records[-1].hash if self._records else ""
        seq = len(self._records) + 1
        ts = utcnow()
        rec = AuditRecord(seq=seq, ts=ts, run_id=entry.run_id, actor=entry.actor, event_type=entry.event_type, payload=payload,
                          prev_hash=prev, hash=_hash(prev, seq, ts.isoformat(), entry, payload))
        self._records.append(rec)
        return rec

    async def list_for_run(self, run_id: str) -> list[AuditRecord]:
        return [r for r in self._records if r.run_id == run_id]

    async def verify_chain(self) -> bool:
        prev = ""
        for r in self._records:
            e = AuditEntryInput(run_id=r.run_id, actor=r.actor, event_type=r.event_type, payload=r.payload)
            if r.prev_hash != prev or r.hash != _hash(prev, r.seq, r.ts.isoformat(), e, r.payload):
                return False
            prev = r.hash
        return True
