"""Structured JSON logging with redaction (secrets never reach a log line)."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.security.keys import Redactor, make_redactor

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_STD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for k, v in record.__dict__.items():
            if k not in _STD_ATTRS and not k.startswith("_"):
                entry[k] = v
        if record.exc_info and record.exc_info[0] is not None:
            entry["exc_type"] = record.exc_info[0].__name__  # type only: messages may contain values
        safe = self._redactor.redact(entry, sink="log")
        try:
            return json.dumps(safe, default=str, separators=(",", ":"))
        except Exception:  # noqa: BLE001 - logging must never raise
            return json.dumps({"level": "ERROR", "message": "[REDACTED:error]"})


def configure_logging(level: str, secret_values: list[str]) -> Redactor:
    redactor = make_redactor(secret_values)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(redactor))
    root = logging.getLogger("liferescue")
    root.handlers = [handler]
    root.setLevel(level.upper() if level.upper() in logging.getLevelNamesMapping() else "INFO")
    root.propagate = False
    return redactor
