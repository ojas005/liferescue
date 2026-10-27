"""SQLite-backed fixed-window rate limiter shared by all workers using one db file (KAN-50)."""

from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from collections.abc import Callable

GLOBAL_AI_KEY = "__global_ai_calls__"
DAILY_AI_KEY = "__daily_ai_calls__"
_PRUNE_EVERY = 500
_BUSY_TIMEOUT_MS = 5000
_INIT_ATTEMPTS = 8
_ALLOW_ATTEMPTS = 3  # bounded retry on transient lock, each bounded by busy_timeout


class RateLimitUnavailable(Exception):
    """The limiter store could not be read/written. Callers must FAIL CLOSED."""


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
        self._ready = False
        with self._lock, contextlib.suppress(RateLimitUnavailable):
            self._init_schema()  # retried lazily in allow() if it could not finish now

    def _init_schema(self) -> None:
        """WAL mode + table, set once; retried with backoff while another process holds a lock."""
        delay = 0.05
        for attempt in range(_INIT_ATTEMPTS):
            try:
                conn = self._conn()
                try:
                    if self._mem is None:
                        conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, "
                        "window_start REAL NOT NULL, count INTEGER NOT NULL)"
                    )
                finally:
                    self._close(conn)
                self._ready = True
                return
            except sqlite3.OperationalError as err:
                if "locked" not in str(err) and "busy" not in str(err):
                    raise RateLimitUnavailable(type(err).__name__) from err
                if attempt + 1 < _INIT_ATTEMPTS:
                    time.sleep(delay)
                    delay = min(delay * 2, 1.0)
            except sqlite3.Error as err:
                raise RateLimitUnavailable(type(err).__name__) from err
        raise RateLimitUnavailable("schema_init_locked")

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
        conn = sqlite3.connect(
            self._path, timeout=_BUSY_TIMEOUT_MS / 1000, isolation_level=None
        )
        conn.execute(
            f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}"
        )  # before any other statement
        return conn

    def _close(self, conn: sqlite3.Connection) -> None:
        if conn is not self._mem:
            conn.close()

    def allow(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds). limit <= 0 means unlimited.

        Raises RateLimitUnavailable on any store error (callers fail closed)."""
        if self.limit <= 0:
            return True, 0
        with self._lock:
            if not self._ready:
                self._init_schema()
            delay = 0.05
            for attempt in range(_ALLOW_ATTEMPTS):
                try:
                    return self._allow(key)
                except sqlite3.OperationalError as err:
                    transient = "locked" in str(err) or "busy" in str(err)
                    if not transient or attempt + 1 == _ALLOW_ATTEMPTS:
                        raise RateLimitUnavailable(type(err).__name__) from err
                    time.sleep(delay)
                    delay *= 2
                except sqlite3.Error as err:
                    raise RateLimitUnavailable(type(err).__name__) from err
            raise RateLimitUnavailable(
                "exhausted"
            )  # unreachable; keeps the loop finite

    def count(self, key: str) -> int:
        """Current-window count for key (diagnostics/tests)."""
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT window_start, count FROM rate_limits WHERE key=?", (key,)
                ).fetchone()
            finally:
                self._close(conn)
        if row is None or self._clock() - row[0] >= self.window_s:
            return 0
        return int(row[1])

    def _allow(self, key: str) -> tuple[bool, int]:
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Read the clock only while holding the write lock, so a caller that waited for
            # the lock cannot see a window that "started in its future" and reset it.
            now = self._clock()
            try:
                row = conn.execute(
                    "SELECT window_start, count FROM rate_limits WHERE key=?",
                    (key,),
                ).fetchone()
                start, count = (now, 0) if row is None else (row[0], row[1])
                if now - start >= self.window_s:
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
                with contextlib.suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                raise
        finally:
            self._close(conn)
