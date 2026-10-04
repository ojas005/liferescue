"""Runtime errors. They extend the platform-contract errors so the API layer maps them uniformly.
Messages are redacted at construction so an exception can never carry a secret into a log or event."""

from __future__ import annotations

from contract import errors as ce

from .redaction import redact_text


class _Redacted:
    def __init__(self, message: str = "") -> None:
        super().__init__(redact_text(str(message), max_len=500))  # type: ignore[call-arg]


class NotConfigured(_Redacted, ce.ConfigError):
    """A required credential/config value (e.g. NEBIUS_API_KEY) is absent. Never includes values."""

    code = "not_configured"


class LimitReached(_Redacted, ce.ContractError):
    """Per-run cap hit (U5): steps, tool calls, wall time or tokens."""

    code = "limit_reached"


class SSRFBlocked(_Redacted, ce.ToolError):
    code = "ssrf_blocked"


class FetchFailed(_Redacted, ce.ToolError):
    code = "fetch_failed"


class SchemaViolation(_Redacted, ce.ContractError):
    """Model plan/args violate the workflow allowlist or a tool schema (U2). Never retried looser."""

    code = "schema_violation"
