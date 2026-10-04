"""SecretBackend protocol (spec section 4.2). Real adapters are deferred (spec section 10)."""
from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from .secret_types import Environment, SecretRef, SecretValue


class SecretBackend(Protocol):
    environment: Environment  # a backend declares which environment it serves

    def resolve(self, ref: SecretRef, *, ttl: timedelta) -> SecretValue: ...

    def revoke(self, ref: SecretRef, lease_id: str) -> None: ...  # best effort at the provider

    def health(self) -> bool: ...
