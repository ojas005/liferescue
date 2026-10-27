"""Logging allow-list for credential paths (KAN-45 spec section 7, step 4).

Rules implemented:
  * A credential event is logged with NAMED FIELDS chosen from an allow-list per event type.
    Everything else is dropped by default.
  * Each allowed field has a strict shape; a value that does not match is replaced by ``invalid``.
  * Free-form log records on a credential logger (message text, args, ``extra`` attributes,
    exception info, stack info) are DROPPED, not redacted: fail closed.
  * The log level never widens the allow-list (DEBUG behaves like INFO).

Redaction of arbitrary text (the safety net on top of this allow-list) is the second PR.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import IO, Mapping

from .audit import AUDIT_FIELDS, AuditEvent, AuditEventType

CREDENTIAL_LOGGER_NAME = "liferescue.secrets"
_MARK = "_kan45_credential_fields"

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_LEASE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_REF = re.compile(r"^secretref://[a-z]{1,16}/[a-z_]{1,32}/[a-z][a-z0-9_-]{0,47}$")
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_WORD = re.compile(r"^[a-z][a-z_]{0,31}$")
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+00:00$")


def _num(v) -> bool:
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and v == v
        and abs(v) < 1e9
    )


def _matches(rx):
    return lambda v: isinstance(v, str) and rx.match(v) is not None


#: field name -> shape check. A field outside this table can never be logged.
FIELD_SHAPES = {
    "event_id": _matches(re.compile(r"^[0-9a-f]{16}$")),
    "event_type": _matches(_WORD),
    "timestamp": _matches(_TIME),
    "correlation_id": _matches(_ID),
    "lease_id": _matches(_LEASE),
    "agent_id": _matches(_ID),
    "task_id": _matches(_ID),
    "run_id": _matches(_ID),
    "ref": _matches(_REF),
    "purpose": _matches(_WORD),
    "environment": _matches(_WORD),
    "reason_code": _matches(_CODE),
    "outcome": _matches(_WORD),
    "error_class": _matches(re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")),
    "ttl_s": _num,
    "latency_ms": _num,
    "alert": lambda v: isinstance(v, bool),
}

_CORE = {
    "event_id",
    "event_type",
    "timestamp",
    "correlation_id",
    "task_id",
    "run_id",
    "agent_id",
    "ref",
    "outcome",
    "reason_code",
    "alert",
}

#: allow-list per event type (spec 7.1). Anything not listed is dropped.
EVENT_ALLOW_LIST = {
    AuditEventType.LEASE_REQUESTED.value: _CORE | {"purpose", "environment", "ttl_s"},
    AuditEventType.LEASE_DENIED.value: _CORE | {"purpose", "environment"},
    AuditEventType.LEASE_ISSUED.value: _CORE
    | {"lease_id", "purpose", "environment", "ttl_s"},
    AuditEventType.LEASE_USED.value: _CORE | {"lease_id", "latency_ms"},
    AuditEventType.LEASE_EXPIRED.value: _CORE | {"lease_id"},
    AuditEventType.LEASE_REVOKED.value: _CORE | {"lease_id"},
    AuditEventType.REDACTION_BLOCKED.value: _CORE | {"purpose"},
    AuditEventType.MISUSE_SUSPECTED.value: _CORE | {"lease_id"},
    AuditEventType.BACKEND_UNHEALTHY.value: _CORE | {"lease_id"},
    # generic bucket for span attributes / exception fields in telemetry (spec 7.6)
    "span": _CORE
    | {"lease_id", "purpose", "environment", "ttl_s", "latency_ms", "error_class"},
}


def allowed_fields(event_type: str) -> frozenset:
    return frozenset(EVENT_ALLOW_LIST.get(event_type, ()))


def sanitize_fields(event_type: str, fields: Mapping, *, leak_check=None) -> dict:
    """Keep only allow-listed fields; replace values with a wrong shape by ``invalid``.

    ``leak_check`` (optional callable ``str -> bool``, e.g. ``redactor.contains_secret``) additionally
    replaces any allowed field that holds a currently leased value by ``redacted``.
    An unknown event type has an empty allow-list, so everything is dropped (fail closed).
    """
    allowed = allowed_fields(event_type)
    out: dict = {}
    if not isinstance(fields, Mapping):
        return out
    for key, value in fields.items():
        if not isinstance(key, str) or key not in allowed:
            continue  # dropped by default; the key name is not logged
        if not FIELD_SHAPES[key](value):
            out[key] = "invalid"
        elif leak_check is not None and isinstance(value, str) and leak_check(value):
            out[key] = "redacted"
        else:
            out[key] = value
    return out


def event_to_log_fields(event: AuditEvent) -> dict:
    data = {k: v for k, v in event.to_dict().items() if v is not None}
    if event.ref:
        # "secretref://<environment>/<purpose>/<name>".split("/") -> ["secretref:", "", env, purpose, name]
        parts = event.ref.split("/")
        if len(parts) == 5:
            data["environment"], data["purpose"] = parts[2], parts[3]
    return data


def log_credential_event(
    logger: logging.Logger, event_type: str, fields: Mapping
) -> None:
    """The only sanctioned way to log on a credential path. Level-independent field selection."""
    clean = sanitize_fields(event_type, fields)
    clean.setdefault(
        "event_type", event_type if event_type in EVENT_ALLOW_LIST else "unknown"
    )
    logger.info("credential_event", extra={_MARK: clean})


class CredentialLogFilter(logging.Filter):
    """Attach to handlers (and loggers) that receive credential-path records.

    Structured records created by ``log_credential_event`` are rewritten to ``name k=v ...`` from the
    already-sanitised fields. Every other record that reaches this filter is dropped.
    """

    def __init__(self) -> None:
        super().__init__()
        self.dropped = 0
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        fields = record.__dict__.get(_MARK)
        if not isinstance(fields, dict):
            with self._lock:
                self.dropped += 1
            return False
        record.msg = "credential_event " + " ".join(
            f"{k}={fields[k]}" for k in sorted(fields)
        )
        record.args = None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        # strip every other custom attribute (extra=...) so a formatter that dumps __dict__ cannot leak
        for key in list(record.__dict__):
            if key not in _STANDARD_RECORD_KEYS and key != _MARK:
                del record.__dict__[key]
        return True


_STANDARD_RECORD_KEYS = set(
    logging.LogRecord("n", logging.INFO, "p", 1, "m", None, None).__dict__
) | {"message", "asctime", "taskName"}


def install_credential_log_filter(logger: logging.Logger) -> CredentialLogFilter:
    """Add one shared filter to ``logger`` and to each of its current handlers."""
    flt = CredentialLogFilter()
    logger.addFilter(flt)
    for handler in logger.handlers:
        handler.addFilter(flt)
    return flt


class LoggingAuditSink:
    """Audit sink that writes allow-listed fields to a logger (spec 7.4 "local audit sink")."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def emit(self, event: AuditEvent) -> None:
        log_credential_event(self._logger, event.event_type, event_to_log_fields(event))


class StreamAuditSink:
    """JSON-lines audit sink for a caller-supplied text stream (no default path; nothing is opened here)."""

    def __init__(self, stream: IO[str]) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def emit(self, event: AuditEvent) -> None:
        record = {k: event.to_dict()[k] for k in AUDIT_FIELDS}
        line = json.dumps(record, sort_keys=True)
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()
