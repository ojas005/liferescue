"""Audit event contract and sinks (KAN-45 spec 7.4, invariant I-6).

An audit event holds ids and metadata only: never a value, never free text from an agent.
Every field is shape-validated when the event is built; a field that does not match its shape
is replaced by ``"invalid"`` (so a hostile string cannot ride into an audit sink).

Until KAN-47 / ADR-0009 define the platform audit format, events go to a local sink with
exactly these fields. The ``alert`` flag is a PROPOSED addition: it is the "alert signal" that
spec I-7 / T-12 / T-13 require for fail-closed and burst conditions.
"""

from __future__ import annotations

import re
import secrets as _stdlib_secrets
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

_ID_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_LEASE_SHAPE = re.compile(
    r"^[A-Za-z0-9_-]{16,64}$"
)  # urlsafe base64 ids may start with "-" or "_"
_REF_SHAPE = re.compile(r"^secretref://[a-z]{1,16}/[a-z_]{1,32}/[a-z][a-z0-9_-]{0,47}$")
_CODE_SHAPE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
OUTCOMES = frozenset(
    {
        "requested",
        "issued",
        "denied",
        "used",
        "expired",
        "revoked",
        "blocked",
        "suspected",
        "unhealthy",
    }
)


class AuditEventType(Enum):
    LEASE_REQUESTED = "lease_requested"
    LEASE_DENIED = "lease_denied"
    LEASE_ISSUED = "lease_issued"
    LEASE_USED = "lease_used"
    LEASE_EXPIRED = "lease_expired"
    LEASE_REVOKED = "lease_revoked"
    REDACTION_BLOCKED = "redaction_blocked"
    MISUSE_SUSPECTED = "misuse_suspected"
    BACKEND_UNHEALTHY = "backend_unhealthy"


AUDIT_FIELDS = (
    "event_id",
    "event_type",
    "timestamp",
    "correlation_id",
    "task_id",
    "run_id",
    "agent_id",
    "lease_id",
    "ref",
    "outcome",
    "reason_code",
    "alert",
)


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    event_type: str
    timestamp: str  # UTC, ISO 8601
    correlation_id: str | None
    task_id: str | None
    run_id: str | None
    agent_id: str | None
    lease_id: str | None
    ref: str | None  # the secretref NAME, never a value
    outcome: str
    reason_code: str | None
    alert: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(value, shape) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and shape.match(value):
        return value
    return "invalid"


def new_event_id() -> str:
    return _stdlib_secrets.token_hex(8)


def make_event(
    event_type: AuditEventType,
    *,
    wall: datetime,
    outcome: str,
    correlation_id=None,
    task_id=None,
    run_id=None,
    agent_id=None,
    lease_id=None,
    ref=None,
    reason_code=None,
    alert: bool = False,
) -> AuditEvent:
    if not isinstance(event_type, AuditEventType):
        raise TypeError("event_type must be an AuditEventType")
    if outcome not in OUTCOMES:
        raise ValueError("unknown outcome")
    if wall.tzinfo is None:
        raise ValueError("wall clock must be timezone-aware")
    return AuditEvent(
        event_id=new_event_id(),
        event_type=event_type.value,
        timestamp=wall.astimezone(UTC).isoformat(),
        correlation_id=_clean(correlation_id, _ID_SHAPE),
        task_id=_clean(task_id, _ID_SHAPE),
        run_id=_clean(run_id, _ID_SHAPE),
        agent_id=_clean(agent_id, _ID_SHAPE),
        lease_id=_clean(lease_id, _LEASE_SHAPE),
        ref=_clean(ref, _REF_SHAPE),
        outcome=outcome,
        reason_code=_clean(reason_code, _CODE_SHAPE),
        alert=bool(alert),
    )


class AuditSink(Protocol):
    def emit(self, event: AuditEvent) -> None: ...


class InMemoryAuditSink:
    """Thread-safe in-memory sink for tests and local use."""

    def __init__(self) -> None:
        self._events: list = []
        self._lock = threading.Lock()

    def emit(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> list:
        with self._lock:
            return list(self._events)

    def of_type(self, event_type: AuditEventType) -> list:
        return [e for e in self.events if e.event_type == event_type.value]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
