"""Clock abstraction (spec 5.2: monotonic clock for duration, wall clock recorded for audit)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def wall(self) -> datetime: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def wall(self) -> datetime:
        return datetime.now(UTC)
