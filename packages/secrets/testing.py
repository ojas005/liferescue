"""Reusable test helpers for the secret-management slice (KAN-45 spec section 1: KAN-46 reuses these).

Nothing here is a credential. Seeded canaries are assembled at call time from a fixed,
non-provider prefix plus random characters, so the repository never contains a whole
realistic key (spec section 8.1) and the values are valid for no provider.
"""

from __future__ import annotations

import secrets as _stdlib_secrets  # stdlib module; see the note in __init__.py
import string
from datetime import datetime, timedelta, timezone

_ALPHABET = string.ascii_letters + string.digits


def random_chars(n: int) -> str:
    """``n`` cryptographically random alphanumeric characters."""
    return "".join(_stdlib_secrets.choice(_ALPHABET) for _ in range(n))


def make_canary(prefix: str = "mock-", length: int = 32) -> str:
    """A fresh random canary: ``prefix + random``. Never reused across calls or runs."""
    return prefix + random_chars(length)


class FakeClock:
    """Controllable clock. ``advance`` moves both clocks; ``jump_wall`` moves only the wall clock."""

    def __init__(
        self, monotonic_start: float = 1000.0, wall_start: datetime | None = None
    ) -> None:
        self._mono = float(monotonic_start)
        self._wall = wall_start or datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
        self.fail_with: Exception | None = None

    def monotonic(self) -> float:
        if self.fail_with is not None:
            raise self.fail_with
        return self._mono

    def wall(self) -> datetime:
        return self._wall

    def advance(self, seconds: float) -> None:
        self._mono += seconds
        self._wall += timedelta(seconds=seconds)

    def jump_wall(self, seconds: float) -> None:
        self._wall += timedelta(seconds=seconds)

    def set_monotonic(self, value: float) -> None:
        self._mono = float(value)
