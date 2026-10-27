"""Exceptions for the secret-management slice (KAN-45).

Rule (spec invariant I-1): no exception raised by this package may carry a request body,
a backend message, a path, or a secret value. Messages are fixed strings or closed-list
codes. Exceptions that wrap a failure are raised *outside* the ``except`` block, so that
``__cause__`` and ``__context__`` never chain to an exception that might hold a value.
"""

from __future__ import annotations

from .codes import DenialReason


class SecretsError(Exception):
    """Base class for all errors raised by packages.secrets."""


class ConfigurationError(SecretsError):
    """Invalid or unsafe configuration. Startup fails closed."""


class PolicyError(ConfigurationError):
    """The policy file is invalid. Fail closed: no credential is issued."""


class InvalidRequest(SecretsError):
    """A request/ref field has an invalid shape. Carries the FIELD NAME only, never the value."""

    def __init__(self, field: str) -> None:
        super().__init__(f"invalid field: {field}")
        self.field = field


class InvalidSecretRef(InvalidRequest):
    """A secretref string or object is invalid (unknown purpose/environment, bad name)."""


class Denied(SecretsError):
    """A credential request or use was refused. ``reason`` is a closed-list code."""

    def __init__(self, reason: DenialReason) -> None:
        super().__init__(f"denied: {reason.value}")
        self.reason = reason


class BackendError(SecretsError):
    """A backend failed. The message is a fixed string; backend details are dropped."""


class UnknownRef(BackendError):
    """The backend has no value for the ref."""


class SecretLeak(SecretsError):
    """Text or data about to be emitted contains a secret. Carries sink and kinds only."""

    def __init__(self, sink: str, kinds: tuple[str, ...] = ()) -> None:
        super().__init__(
            f"secret leak blocked at sink={sink} kinds={','.join(kinds) or 'unknown'}"
        )
        self.sink = sink
        self.kinds = kinds


class SecretWiped(SecretsError):
    """A SecretValue was used after being wiped."""
