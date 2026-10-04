"""Memory interface: per-run and per-user scopes. In-memory default; LR 04 may back it with Postgres.
Values are stored redacted (a secret must never persist in memory)."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from .redaction import redact_payload


class MemoryScope(StrEnum):
    RUN = "run"
    USER = "user"


@runtime_checkable
class Memory(Protocol):
    async def put(self, scope: MemoryScope, owner_id: str, key: str, value: Any) -> None: ...

    async def get(
        self, scope: MemoryScope, owner_id: str, key: str, default: Any = None
    ) -> Any: ...

    async def items(self, scope: MemoryScope, owner_id: str) -> dict[str, Any]: ...

    async def delete(self, scope: MemoryScope, owner_id: str, key: str | None = None) -> None:
        """Delete one key, or the whole scope/owner bucket when key is None (retention, P4)."""
        ...


class InMemoryMemory:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def put(self, scope: MemoryScope, owner_id: str, key: str, value: Any) -> None:
        async with self._lock:
            self._data.setdefault((scope.value, owner_id), {})[key] = redact_payload(value)

    async def get(self, scope: MemoryScope, owner_id: str, key: str, default: Any = None) -> Any:
        async with self._lock:
            return self._data.get((scope.value, owner_id), {}).get(key, default)

    async def items(self, scope: MemoryScope, owner_id: str) -> dict[str, Any]:
        async with self._lock:
            return dict(self._data.get((scope.value, owner_id), {}))

    async def delete(self, scope: MemoryScope, owner_id: str, key: str | None = None) -> None:
        async with self._lock:
            if key is None:
                self._data.pop((scope.value, owner_id), None)
            else:
                self._data.get((scope.value, owner_id), {}).pop(key, None)
