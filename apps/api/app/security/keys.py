"""Single place that knows how to reach the credential broker package (KAN-45).

The KAN-45 package is ``packages/secrets`` on ``main`` (the scratch tree this was written on called it
``packages/credential_broker``; both names are tried). If it is renamed again, change ``CANDIDATE_MODULES`` only.
If none is importable with its ``redaction`` module (e.g. KAN-45 PR #7 is not merged yet) a minimal,
stricter-than-nothing fallback redactor is used and ``BROKER_AVAILABLE`` is False.

This module is also the ONLY place in apps/api that reads key material from the environment (SECURITY-REQUIREMENTS K1):
``known_secret_values`` feeds the redactor, ``key_status`` reports presence as yes/no, ``require_key`` fails startup
without ever echoing a value. Model/Tavily adapters (LR 06) must obtain their key through ``get_key``.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from contract.errors import ConfigError

CANDIDATE_MODULES = ("packages.credential_broker", "packages.secrets")  # swap the name HERE only

# apps/api/app/security/keys.py -> repo root is parents[4]; add it LAST so it can never shadow anything.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if (_REPO_ROOT / "packages").is_dir() and str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

MARKER = "[REDACTED:{}]"

KEY_ENV_NAMES = ("NEBIUS_API_KEY", "TAVILY_API_KEY")  # env only; never in files, compose, images or logs


def get_key(name: str, env: Mapping[str, str] | None = None) -> str | None:
    """The single read of a provider key from the environment. Callers must wrap it (SecretStr / broker lease)."""
    if name not in KEY_ENV_NAMES:
        raise ValueError("unknown key name")
    return (os.environ if env is None else env).get(name) or None


def key_status(env: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Presence only (K1: log 'key present: yes/no', never the value or its length)."""
    return {n: get_key(n, env) is not None for n in KEY_ENV_NAMES}


def require_key(name: str, env: Mapping[str, str] | None = None) -> None:
    if get_key(name, env) is None:
        raise ConfigError(
            f"{name} is required by the selected configuration but is not set in the environment"
        )


def known_secret_values(extra: list[str] | None = None, env: Mapping[str, str] | None = None) -> list[str]:
    """Raw secret values to hide in logs/DB/responses. Never log or return this list."""
    vals = [v for n in KEY_ENV_NAMES if (v := get_key(n, env))]
    return vals + [v for v in (extra or []) if v]


class Redactor(Protocol):
    def redact(self, obj: Any, *, sink: str = "unknown") -> Any: ...
    def redact_text(self, text: str, *, sink: str = "unknown") -> str: ...


# ---- fallback -----------------------------------------------------------------------------------
_DENIED_KEY = re.compile(
    r"password|passwd|secret|token|api_?key|authorization|cookie|private_?key|credential|connection_string",
    re.IGNORECASE,
)
_PATTERNS = [
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")),
    ("api_key", re.compile(r"\b(?:sk|pk|tvly|nvapi|ghp|gho|xox[bap])[-_][A-Za-z0-9_-]{12,}")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("url_password", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+):[^\s@/]+@")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # P2 (PII minimisation): Aadhaar (grouped 4-4-4), PAN, OTP/CVV/PIN assignments. Card numbers: see _mask_cards.
    ("aadhaar", re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}\b")),
    ("pan", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    (
        "otp",
        re.compile(r"(?i)\b(?:otp|cvv|cvc|pin|one[- ]time (?:password|code|pin))\b[\s:=is]{0,6}\d{3,8}\b"),
    ),
]
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _mask_cards(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        return MARKER.format("card") if 13 <= len(digits) <= 19 and _luhn_ok(digits) else m.group(0)

    return _CARD.sub(repl, text)


class FallbackRedactor:
    """Minimal redactor used only when the credential broker package is not importable."""

    def __init__(self, extra_values: list[str] | None = None) -> None:
        self._values = sorted({v for v in (extra_values or []) if v}, key=len, reverse=True)

    def redact_text(self, text: str, *, sink: str = "unknown") -> str:
        for v in self._values:
            text = text.replace(v, MARKER.format("secret"))
        for kind, pat in _PATTERNS:
            if kind == "url_password":
                text = pat.sub(lambda m: m.group(1) + ":" + MARKER.format("url_password") + "@", text)
            else:
                text = pat.sub(MARKER.format(kind), text)
        return _mask_cards(text)

    def redact(self, obj: Any, *, sink: str = "unknown", _depth: int = 0) -> Any:
        if _depth > 20:
            return MARKER.format("error")
        if isinstance(obj, str):
            return self.redact_text(obj, sink=sink)
        if isinstance(obj, dict):
            return {
                k: (
                    MARKER.format("field")
                    if isinstance(k, str) and _DENIED_KEY.search(k)
                    else self.redact(v, sink=sink, _depth=_depth + 1)
                )
                for k, v in obj.items()
            }
        if isinstance(obj, (list, tuple, set, frozenset)):
            return [self.redact(v, sink=sink, _depth=_depth + 1) for v in obj]
        if obj is None or isinstance(obj, (int, float, bool)):
            return obj
        return MARKER.format("object")


def _load_broker_module() -> Any | None:
    """First candidate package that is importable AND provides ``redaction`` (the part this module uses).

    On ``main`` ``packages/secrets`` exists before its ``redaction`` module is merged (KAN-45 PR #7); in that case
    the package is skipped and the local fallback redactor is used, instead of failing at ``make_redactor``."""
    for name in CANDIDATE_MODULES:
        try:
            module = importlib.import_module(name)
            importlib.import_module(name + ".redaction")
            return module
        except ImportError:
            continue
    return None


_broker = _load_broker_module()
BROKER_AVAILABLE: bool = _broker is not None
BROKER_MODULE_NAME: str | None = _broker.__name__ if _broker is not None else None


class LayeredRedactor:
    """Broker redactor first (known values in many encodings, gitleaks-mirrored patterns, key-name rule),
    then the local pattern layer for provider-key shapes the broker's pattern set does not cover
    (sk-/tvly-/nvapi- ..., Bearer, URL passwords). Both layers only ever emit ``[REDACTED:<kind>]``."""

    def __init__(self, primary: Redactor, secondary: FallbackRedactor) -> None:
        self._primary = primary
        self._secondary = secondary

    def redact(self, obj: Any, *, sink: str = "unknown") -> Any:
        return self._secondary.redact(self._primary.redact(obj, sink=sink), sink=sink)

    def redact_text(self, text: str, *, sink: str = "unknown") -> str:
        return self._secondary.redact_text(self._primary.redact_text(text, sink=sink), sink=sink)


def make_redactor(extra_values: list[str] | None = None) -> Redactor:
    """Redactor that hides ``extra_values`` (and encodings of them, when the broker is available)."""
    fallback = FallbackRedactor(extra_values)
    if _broker is not None:
        mod = importlib.import_module(_broker.__name__ + ".redaction")
        primary: Redactor = mod.Redactor(extra_values=list(extra_values or []))
        return LayeredRedactor(primary, fallback)
    return fallback
