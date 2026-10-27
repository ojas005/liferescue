"""Counters only (spec section 11): no labels with task text or identifiers beyond closed-list codes."""

from __future__ import annotations

import threading
from collections import Counter


class Metrics:
    def __init__(self) -> None:
        self._counts: Counter = Counter()
        self._lock = threading.Lock()

    def inc(self, name: str, label: str = "") -> None:
        with self._lock:
            self._counts[(name, label)] += 1

    def get(self, name: str, label: str = "") -> int:
        with self._lock:
            return self._counts[(name, label)]

    def total(self, name: str) -> int:
        with self._lock:
            return sum(v for (n, _), v in self._counts.items() if n == name)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                f"{n}{{{l}}}" if l else n: v
                for (n, l), v in sorted(self._counts.items())
            }
