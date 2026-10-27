"""SQLite-backed fixed-window rate limiter shared by all workers using one db file (KAN-50)."""

from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from collections.abc import Callable

GLOBAL_AI_KEY = "__global_ai_calls__"
_PRUNE_EVERY = 500


def store_path_for(db_path: str) -> str:
    return ":memory:" if db_path in ("", ":memory:") else f"{db_path}.ratelimit"


class RateLimiter:
    """Fixed-window counter in SQLite; atomic across threads and processes (BEGIN IMMEDIATE)."""

    def __init__(
        self,
        limit: int,
        window_s: float,
        db_path: str = ":memory:",
        clock: Callable[[], float] = time.time,
    ):
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._lock = threading.Lock()
        self._calls = 0
        self._path = db_path
        self._mem: sqlite3.Connection | None = None
        if db_path == ":memory:":
            self._mem = sqlite3.connect(
                ":memory:", check_same_thread=False, isolation_level=None
            )
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS rate_limits ("
                    "key TEXT PRIMARY KEY, window_start REAL NOT NULL, count INTEGER NOT NULL)"
                )
            finally:
                self._close(conn)

    def close(self) -> None:
        if self._mem is not None:
            self._mem.close()
            self._mem = None

    def __del__(self) -> None:
        with contextlib.suppress(Exception):  # best effort at interpreter shutdown
            self.close()

    def _conn(self) -> sqlite3.Connection:
        if self._path == ":memory:":
            if self._mem is None:
                raise RuntimeError("rate limiter closed")
            return self._mem
        conn = sqlite3.connect(self._path, timeout=5.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _close(self, conn: sqlite3.Connection) -> None:
        if conn is not self._mem:
            conn.close()

    def allow(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds). limit <= 0 means unlimited."""
        if self.limit <= 0:
            return True, 0
        now = self._clock()
        with self._lock:
            conn = self._conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    row = conn.execute(
                        "SELECT window_start, count FROM rate_limits WHERE key=?",
                        (key,),
                    ).fetchone()
                    start, count = (now, 0) if row is None else (row[0], row[1])
                    if now - start >= self.window_s or now < start:
                        start, count = now, 0
                    if count >= self.limit:
                        conn.execute("COMMIT")
                        return False, max(1, int(self.window_s - (now - start)) + 1)
                    conn.execute(
                        "INSERT INTO rate_limits(key, window_start, count) VALUES(?,?,?) "
                        "ON CONFLICT(key) DO UPDATE SET window_start=excluded.window_start, "
                        "count=excluded.count",
                        (key, start, count + 1),
                    )
                    self._calls += 1
                    if self._calls % _PRUNE_EVERY == 0:
                        conn.execute(
                            "DELETE FROM rate_limits WHERE window_start < ?",
                            (now - self.window_s,),
                        )
                    conn.execute("COMMIT")
                    return True, 0
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            finally:
                self._close(conn)
