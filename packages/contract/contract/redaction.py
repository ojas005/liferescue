"""Minimal payload redaction for timeline events and audit records (ASSUMPTION: key-name based)."""
from __future__ import annotations

import re
from typing import Any

_SECRET_KEY = re.compile(r"(api[_-]?key|token|secret|password|passwd|authorization|credential|cookie)", re.I)
_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{8,}")
MASK = "[REDACTED]"


def redact_payload(value: Any) -> Any:
    """Return a copy with secret-looking keys masked and bearer tokens removed from strings."""
    if isinstance(value, dict):
        return {k: (MASK if _SECRET_KEY.search(str(k)) else redact_payload(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_payload(v) for v in value]
    if isinstance(value, str):
        return _BEARER.sub(MASK, value)
    return value
