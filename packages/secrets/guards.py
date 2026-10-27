"""Sink guards (KAN-45 spec 6.7-6.11, step 5): prompt builder, persistence, return path, outgoing text,
log filter and audit writer. Each guard uses the broker's redactor, so it knows every currently leased value.

Fail-closed rule: a guard that finds a secret REFUSES (``SecretLeak``) rather than sending a redacted
variant, except on the return path to an agent (spec 6.10: "redacted before return") and in logs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from .audit import AuditEvent, AuditSink
from .errors import SecretLeak
from .logging_rules import _STANDARD_RECORD_KEYS
from .redaction import Redactor

#: Closed list of sink names; anything else is counted as "unknown".
SINKS = frozenset(
    {
        "prompt",
        "log",
        "persistence",
        "return",
        "audit",
        "outgoing",
        "telemetry",
        "error",
        "unknown",
    }
)


def _digest(obj: Any) -> str:
    try:
        raw = json.dumps(obj, sort_keys=True, default=lambda o: type(o).__name__)
    except (TypeError, ValueError):
        raw = repr(type(obj))
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def redact_record_message(record: logging.LogRecord, message: str, redact) -> None:
    """LR 08 N-04: redact a record WITHOUT discarding ``record.args``.

    uvicorn's AccessFormatter unpacks ``record.args`` (5-tuple); setting it to None crashed the access
    line. Tuple args are redacted element-wise and kept; if that cannot reproduce the fully redacted
    message (secret spanning args, non-str arg), fall back to a pre-formatted message with string args
    of the same arity (``%s``-only formats such as uvicorn's still render; others lose the line safely).
    """
    redacted = redact(message)
    args = record.args
    if isinstance(args, tuple) and args:
        record.msg = redact(str(record.msg))
        record.args = tuple(redact(a) if isinstance(a, str) else a for a in args)
        try:
            ok = record.getMessage() == redacted
        except Exception:  # noqa: BLE001 - fail-safe: use the collapsed form below
            ok = False
        if ok:
            return
        record.msg = redacted
        record.args = ()
        return
    if redacted != message or args:
        record.msg = redacted
        record.args = ()


class SinkGuards:
    """Guards bound to one broker. ``broker`` must provide ``assert_safe_to_emit_obj`` and ``redactor``."""

    def __init__(self, broker, *, max_blocked_digests: int = 1000) -> None:
        self._broker = broker
        self._redactor: Redactor = broker.redactor
        self._blocked: set = set()
        self._max_blocked = max_blocked_digests
        self._lock = threading.Lock()

    # ---- prompt builder (6.8) ----
    def prompt(self, content: Any) -> Any:
        """Check text (or a tool-result/message structure) before it goes to a model.

        A hit stops the step (SecretLeak), the broker emits a ``redaction_blocked`` event, and the same
        content is never accepted again (no retry with the same text)."""
        digest = _digest(content)
        with self._lock:
            if digest in self._blocked:
                raise SecretLeak("prompt", ("retry_of_blocked",))
        try:
            self._broker.assert_safe_to_emit_obj(content, sink="prompt")
        except SecretLeak:
            with self._lock:
                if len(self._blocked) >= self._max_blocked:
                    self._blocked.clear()
                self._blocked.add(digest)
            raise
        return content

    # ---- persistence (6.9) ----
    def persist(self, record: Mapping, write: Callable[[Mapping], None]) -> None:
        """Database/checkpoint/event writes: refuse the whole write if any key or value holds a secret."""
        self._broker.assert_safe_to_emit_obj(record, sink="persistence")
        write(record)

    # ---- outgoing text for Jira / PR / chat helpers ----
    def outgoing(self, text: str) -> str:
        """Text leaving for an external system. Refused (not redacted) if it holds a secret: sending is irreversible."""
        self._broker.assert_safe_to_emit_obj(text, sink="outgoing")
        return text

    # ---- return path (6.7, 6.10) ----
    def return_path(self, response: Any) -> Any:
        """Response to an agent: redacted structure/text (key-name rule applied)."""
        return self._redactor.redact(response, sink="return")

    def run_provider_call(self, call: Callable[[], Any]) -> Mapping:
        """Run a gateway call. Success: redacted result. Failure: a redacted error result, never a raised
        exception that could carry a provider error body (T-21)."""
        try:
            result = call()
        except Exception as exc:  # noqa: BLE001 - this is the boundary that must not leak
            summary = {
                "ok": False,
                "error_class": type(exc).__name__,
                "error": self._redactor.redact_exception(exc, sink="return"),
            }
            return summary
        return {"ok": True, "result": self.return_path(result)}


class RedactingLogFilter(logging.Filter):
    """General-purpose log filter (spec 6.2/6.7): redacts message, args, extras, exception text, stack text.

    Attach it to HANDLERS (loggers' filters do not run for records propagated from child loggers).
    Credential-path loggers should additionally use ``logging_rules.CredentialLogFilter`` (allow-list)."""

    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._r = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - fail-closed boundary: any failure becomes a denial/fallback and never propagates
            message = "[unformattable log message dropped]"
        redact_record_message(
            record, message, lambda t: self._r.redact_text(t, sink="log")
        )
        if record.exc_info:
            exc = record.exc_info[1]
            record.exc_text = (
                self._r.format_traceback(exc, sink="log") if exc is not None else None
            )
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = self._r.redact_text(record.exc_text, sink="log")
        if record.stack_info:
            record.stack_info = self._r.redact_text(record.stack_info, sink="log")
        for key in list(record.__dict__):
            if key not in _STANDARD_RECORD_KEYS:
                record.__dict__[key] = self._r.redact(record.__dict__[key], sink="log")
        return True


class RedactingAuditSink:
    """Wraps an audit sink so that no event field can carry a currently leased value (spec 6.2: audit writer)."""

    def __init__(self, inner: AuditSink, redactor: Redactor) -> None:
        self._inner = inner
        self._r = redactor

    def emit(self, event: AuditEvent) -> None:
        fixed = {}
        for name, value in event.to_dict().items():
            if isinstance(value, str) and self._r.contains_secret(value):
                fixed[name] = "redacted"
                self._r._count("secret", "audit")
        self._inner.emit(replace(event, **fixed) if fixed else event)

    def __getattr__(
        self, name: str
    ):  # expose the inner sink's helpers (events, of_type, clear) for local sinks
        return getattr(self._inner, name)
