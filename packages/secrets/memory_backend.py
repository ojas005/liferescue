"""In-memory MOCK backend (spec 5.4). The only backend in this slice.

Properties (tested, T-15): reads no environment variable, no file, no network; values come
from a cryptographically strong random source and carry the visible non-provider prefix
``mock-`` so they cannot be mistaken for real keys.
"""
from __future__ import annotations

import secrets as _stdlib_secrets
import threading
from datetime import timedelta
from typing import Optional

from .errors import BackendError, UnknownRef
from .secret_types import Environment, SecretRef, SecretValue

MOCK_PREFIX = "mock-"


class InMemoryBackend:
    environment = Environment.MOCK

    def __init__(self) -> None:
        self._values: dict = {}
        self._lock = threading.Lock()
        self._healthy = True
        self._fail_next: Optional[BaseException] = None
        self.resolve_count = 0
        self.revoked: list = []  # (ref, lease_id) pairs, for tests and the conformance suite

    # ---- setup / test controls -------------------------------------------------------
    def provision(self, ref: SecretRef, value: Optional[str] = None) -> None:
        """Make ``ref`` resolvable. ``value`` defaults to ``mock-`` + 24 random bytes (urlsafe).

        An explicit ``value`` exists so tests can seed a canary they generated at runtime.
        """
        if not isinstance(ref, SecretRef) or ref.environment is not Environment.MOCK:
            raise BackendError("mock backend serves only mock refs")
        if value is None:
            value = MOCK_PREFIX + _stdlib_secrets.token_urlsafe(24)
        if not isinstance(value, str) or not value:
            raise BackendError("value must be a non-empty string")
        with self._lock:
            self._values[ref] = value

    def set_healthy(self, healthy: bool) -> None:
        self._healthy = bool(healthy)

    def fail_next_resolve(self, exc: BaseException) -> None:
        """Test hook: the next ``resolve`` raises ``exc`` (which may carry a canary in its message)."""
        self._fail_next = exc

    # ---- SecretBackend ---------------------------------------------------------------
    def resolve(self, ref: SecretRef, *, ttl: timedelta) -> SecretValue:
        if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
            raise BackendError("ttl must be positive")
        if self._fail_next is not None:
            exc, self._fail_next = self._fail_next, None
            raise exc
        if not self._healthy:
            raise BackendError("backend unhealthy")
        if not isinstance(ref, SecretRef) or ref.environment is not Environment.MOCK:
            raise BackendError("mock backend serves only mock refs")
        with self._lock:
            raw = self._values.get(ref)
            self.resolve_count += 1
        if raw is None:
            raise UnknownRef("unknown ref")
        return SecretValue(raw)

    def revoke(self, ref: SecretRef, lease_id: str) -> None:
        with self._lock:
            self.revoked.append((ref, lease_id))

    def health(self) -> bool:
        return self._healthy
