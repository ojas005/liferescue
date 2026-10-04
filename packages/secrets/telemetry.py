"""Telemetry/trace sanitising (KAN-45 spec 7.6, T-18).

Span attributes and exception data pass through the same allow-list as logs. Exception MESSAGES
are never exported: only the exception class name is.
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

from .logging_rules import sanitize_fields

SPAN_EVENT_TYPE = "span"


def sanitize_span_attributes(attributes: Mapping) -> dict:
    """Allow-listed, shape-checked span attributes. Unknown keys are dropped."""
    return sanitize_fields(SPAN_EVENT_TYPE, attributes)


def exception_fields(exc: Optional[BaseException]) -> dict:
    """What may be exported about an exception: its class name only (no message, args, cause or traceback)."""
    if exc is None:
        return {}
    return sanitize_fields(SPAN_EVENT_TYPE, {"error_class": type(exc).__name__})


class SafeSpanExporter:
    """Wraps an exporter callable ``export(name, attributes)`` so only sanitised data leaves the process."""

    def __init__(self, export: Callable[[str, dict], None]) -> None:
        self._export = export

    def record_span(self, name: str, attributes: Optional[Mapping] = None, exc: Optional[BaseException] = None) -> None:
        safe_name = name if isinstance(name, str) and name.replace("_", "").replace(".", "").isalnum() and len(name) <= 64 else "invalid"
        attrs = sanitize_span_attributes(attributes or {})
        attrs.update(exception_fields(exc))
        self._export(safe_name, attrs)
