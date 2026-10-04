"""Secret redaction for events, logs, audit entries and error messages.

Three layers: (1) exact values of known secrets (registered or harvested from environment
variables whose names look secret), (2) well-known token shapes, (3) key-name based masking of
mapping values. The redactor is deliberately over-eager: a false positive hides a harmless string,
a false negative leaks a credential.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_SECRET_ENV_NAME = re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)S?$", re.I)
_MIN_SECRET_LEN = 8

_registered: set[str] = set()
_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Add an exact secret value to the redaction set (e.g. a key passed in explicitly)."""
    if value and len(value) >= _MIN_SECRET_LEN:
        with _lock:
            _registered.add(value)


def clear_registered_secrets() -> None:
    """Test helper."""
    with _lock:
        _registered.clear()


def _known_secret_values() -> list[str]:
    values = set(_registered)
    for name, val in os.environ.items():
        if val and len(val) >= _MIN_SECRET_LEN and _SECRET_ENV_NAME.search(name):
            values.add(val)
    return sorted(values, key=len, reverse=True)


_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{6,}"), f"Bearer {REDACTED}"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    (
        re.compile(
            r"\b(?:sk|pk|rk|tvly|ghp|gho|ghu|ghs|ghr|glpat|xox[abprs])[-_][A-Za-z0-9_-]{8,}"
        ),
        REDACTED,
    ),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{12,}\b"), REDACTED),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), REDACTED),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|token|secret|"
            r"password|passwd|authorization)(\s*[=:]\s*)([\"']?)[^\s\"',;&]+"
        ),
        rf"\1\2\3{REDACTED}",
    ),
    (re.compile(r"(?i)(://)[^/\s:@]+:[^/\s@]+@"), rf"\1{REDACTED}@"),
]

_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|apikey|secret|passw(?:or)?d|authorization|cookie|credential|private[_-]?key|"
    r"bearer|(?:^|[_-])token$|access[_-]?token|auth[_-]?token)",
    re.I,
)


def redact_text(text: str, *, max_len: int | None = None) -> str:
    """Mask known secrets and token-shaped substrings in a string."""
    if not text:
        return text
    out = text
    for secret in _known_secret_values():
        if secret in out:
            out = out.replace(secret, REDACTED)
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    if max_len is not None and len(out) > max_len:
        out = out[:max_len] + f"...[truncated {len(out) - max_len} chars]"
    return out


_PII_ALWAYS = [
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD]"),  # payment card numbers
    (re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"), "[AADHAAR]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN]"),
    (re.compile(r"(?i)\b(otp|pin|cvv|cvc)\b\s*(?:is|:|=)?\s*\d{3,8}\b"), r"\1 [MASKED]"),
]
_PII_CONTACT = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    (re.compile(r"(?<!\w)\+?\d[\d -]{7,}\d(?!\w)"), "[PHONE]"),
]


def mask_pii(text: str, *, include_contacts: bool = False) -> str:
    """Mask cards, Aadhaar, PAN, OTP/PIN/CVV (always) and e-mail/phone (include_contacts=True, used
    for queries leaving the platform, checklist P2/S6). Applied BEFORE storage/model/search."""
    out = text
    for pat, repl in _PII_ALWAYS + (_PII_CONTACT if include_contacts else []):
        out = pat.sub(repl, out)
    return out


def is_sensitive_key(key: object) -> bool:
    return bool(_SENSITIVE_KEY.search(str(key)))


def redact_payload(
    obj: Any, *, max_str: int = 2000, max_items: int = 50, max_depth: int = 8, _depth: int = 0
) -> Any:
    """Return a JSON-safe, redacted, size-capped copy of `obj` (never mutates the input)."""
    if _depth > max_depth:
        return "[max depth]"
    if obj is None or isinstance(obj, bool | int | float):
        return obj
    if isinstance(obj, str):
        return redact_text(obj, max_len=max_str)
    if isinstance(obj, bytes | bytearray):
        return f"[{len(obj)} bytes]"
    if hasattr(obj, "model_dump"):
        try:
            return redact_payload(
                obj.model_dump(mode="json"),
                max_str=max_str,
                max_items=max_items,
                max_depth=max_depth,
                _depth=_depth,
            )
        except Exception:
            return "[unserializable]"
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(obj.items()):
            if i >= max_items:
                out["..."] = f"[{len(obj) - max_items} more keys]"
                break
            ks = redact_text(str(k), max_len=200)
            out[ks] = (
                REDACTED
                if is_sensitive_key(k) and v not in (None, "")
                else redact_payload(
                    v, max_str=max_str, max_items=max_items, max_depth=max_depth, _depth=_depth + 1
                )
            )
        return out
    if isinstance(obj, list | tuple | set | frozenset):
        items = list(obj)
        res = [
            redact_payload(
                v, max_str=max_str, max_items=max_items, max_depth=max_depth, _depth=_depth + 1
            )
            for v in items[:max_items]
        ]
        if len(items) > max_items:
            res.append(f"[{len(items) - max_items} more items]")
        return res
    return redact_text(str(obj), max_len=max_str)


class RedactingFilter(logging.Filter):
    """Logging filter that redacts the formatted message and args of every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        record.msg = redact_text(msg)
        record.args = ()
        return True


# K2: SDK/httpx loggers can include URLs/headers at INFO; keep them quiet.
for _noisy in ("httpx", "httpcore", "openai", "hpack"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a runtime logger whose records always pass through the redacting filter."""
    logger = logging.getLogger(f"liferescue.runtime.{name}")
    if not any(isinstance(f, RedactingFilter) for f in logger.filters):
        logger.addFilter(RedactingFilter())
    return logger
