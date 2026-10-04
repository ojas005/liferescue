"""The set of currently leased values, in memory only (spec 6.2).

The broker adds a value when a lease is issued and removes it when the lease expires or is
revoked. The redaction library (second PR) reads this set to remove exact occurrences from
text. ``_raw_values`` is internal to this package; do not call it from gateway or agent code.
"""
from __future__ import annotations

import threading

from .secret_types import SecretValue


class LeasedValues:
    def __init__(self) -> None:
        self._values: dict = {}
        self._lock = threading.Lock()

    def add(self, lease_id: str, value: SecretValue) -> None:
        with self._lock:
            self._values[lease_id] = value

    def discard(self, lease_id: str) -> None:
        with self._lock:
            self._values.pop(lease_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)

    def _raw_values(self) -> list:
        with self._lock:
            values = list(self._values.values())
        out = []
        for v in values:
            if not v.wiped:
                with v.reveal() as raw:
                    out.append(raw)
        return out

    def __repr__(self) -> str:
        return f"LeasedValues(count={len(self)})"
