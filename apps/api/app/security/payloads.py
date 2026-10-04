"""One write-time cleaning function for everything that is persisted or logged (SECURITY K3, P1, P2).

Order: contract key-name redaction -> credential_broker/local pattern redaction (known env secrets, key shapes,
card/Aadhaar/PAN/OTP). Idempotent. Never raises (a failure yields a marker, fail closed)."""

from __future__ import annotations

from typing import Any

from contract.redaction import redact_payload

from app.security.keys import Redactor


def clean_payload(redactor: Redactor, payload: dict[str, Any], *, sink: str = "db") -> dict[str, Any]:
    try:
        out = redactor.redact(redact_payload(payload), sink=sink)
        return out if isinstance(out, dict) else {"redacted": True}
    except Exception:  # noqa: BLE001
        return {"redacted": True, "error": "redaction_failed"}


def clean_text(redactor: Redactor, text: str | None, *, sink: str = "db") -> str | None:
    if text is None:
        return None
    try:
        return redactor.redact_text(text, sink=sink)
    except Exception:  # noqa: BLE001
        return "[REDACTED:error]"
