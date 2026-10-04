"""Event fan-out. The authoritative timeline is `RunStore.append_event` (contract; LR 04 persists it).
`EventSink` is an optional second, injectable destination (SSE push, metrics, tests)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from contract.models import TimelineEvent


@runtime_checkable
class EventSink(Protocol):
    async def emit(self, event: TimelineEvent) -> None: ...


class InMemoryEventSink:
    def __init__(self) -> None:
        self.events: list[TimelineEvent] = []

    async def emit(self, event: TimelineEvent) -> None:
        self.events.append(event)

    def for_run(self, run_id: str) -> list[TimelineEvent]:
        return [e for e in self.events if e.run_id == run_id]
