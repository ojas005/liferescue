"""ORM tables. The contract models (contract.models) are the shape; rows hold queryable columns plus the full
contract record as JSON where that is simpler (runs.record)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from contract.models import ApprovalStatus, EventType, RunState
from sqlalchemy import DDL, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, BigIntPK, JSONType, UTCDateTime
from app.db.ddl import POSTGRES_AUDIT_APPEND_ONLY, SQLITE_AUDIT_APPEND_ONLY


def _in(col: str, enum: type[Enum]) -> str:
    return f"{col} IN ({', '.join(repr(e.value) for e in enum)})"


class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (CheckConstraint(_in("state", RunState), name="ck_runs_state"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), index=True)
    workflow_version: Mapped[str] = mapped_column(String(32))
    contract_version: Mapped[str] = mapped_column(String(16))
    owner: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[int] = mapped_column(Integer)  # optimistic concurrency (RunRecord.version)
    record: Mapped[dict[str, Any]] = mapped_column(JSONType)  # full RunRecord (input already redacted)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class RunEventRow(Base):
    """Timeline. Payloads are allowlisted + redacted before insert (P1/K3)."""

    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
        CheckConstraint(_in("step", RunState), name="ck_run_events_step"),
        CheckConstraint(_in("type", EventType), name="ck_run_events_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(UTCDateTime)
    step: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    __table_args__ = (CheckConstraint(_in("status", ApprovalStatus), name="ck_approvals_status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[str] = mapped_column(String(64))
    bound_digest: Mapped[str] = mapped_column(String(64))  # ActionRequest.digest() (sha256 hex)
    status: Mapped[str] = mapped_column(String(16), index=True)
    risk: Mapped[str] = mapped_column(String(16))
    summary: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(64))
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(Text)
    content: Mapped[dict[str, Any]] = mapped_column(JSONType)  # redacted
    trust: Mapped[str] = mapped_column(String(16))
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime)
    sha256: Mapped[str] = mapped_column(String(64))


class AuditRow(Base):
    """Append-only (DB triggers + privileges). Global SHA-256 hash chain (PROPOSED ASSUMPTION, contract/ADR-0009)."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_run_id", "run_id"),)

    seq: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime)
    run_id: Mapped[str] = mapped_column(String(64))  # no FK on purpose: audit outlives run deletion (P4)
    actor: Mapped[str] = mapped_column(String(160))
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)  # redacted
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


for _stmt in POSTGRES_AUDIT_APPEND_ONLY:
    _pg = DDL(_stmt)  # type: ignore[no-untyped-call]
    event.listen(AuditRow.__table__, "after_create", _pg.execute_if(dialect="postgresql"))
for _stmt in SQLITE_AUDIT_APPEND_ONLY:
    _sl = DDL(_stmt)  # type: ignore[no-untyped-call]
    event.listen(AuditRow.__table__, "after_create", _sl.execute_if(dialect="sqlite"))
