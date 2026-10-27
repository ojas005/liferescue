"""Task liveness (spec 4.3 rule 4). The orchestrator provides this; if it is unavailable the broker fails closed.

``InMemoryTaskRegistry`` is a MOCK of the orchestrator for tests and local use.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Protocol

from .codes import RevokeReason


class TaskRegistry(Protocol):
    def is_live(self, task_id: str, run_id: str, agent_id: str) -> bool:
        """True only if the task is running AND (run_id, agent_id) match its registration."""
        ...


class TaskState(Enum):
    RUNNING = "running"
    ENDING = "ending"  # not live any more; leases are being revoked; not yet finished
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STOPPED = "stopped"


_END_REASON = {
    TaskState.COMPLETED: RevokeReason.TASK_END,
    TaskState.FAILED: RevokeReason.TASK_FAILED,
    TaskState.CANCELLED: RevokeReason.TASK_CANCELLED,
    TaskState.STOPPED: RevokeReason.STOP,
}


class InMemoryTaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict = {}
        self._lock = threading.Lock()
        self.unavailable = (
            False  # test hook: simulate the orchestrator being unreachable
        )

    def register(self, task_id: str, run_id: str, agent_id: str) -> None:
        with self._lock:
            self._tasks[task_id] = [run_id, agent_id, TaskState.RUNNING]

    def is_live(self, task_id: str, run_id: str, agent_id: str) -> bool:
        if self.unavailable:
            raise ConnectionError("orchestrator unavailable")
        with self._lock:
            entry = self._tasks.get(task_id)
        return bool(
            entry
            and entry[0] == run_id
            and entry[1] == agent_id
            and entry[2] is TaskState.RUNNING
        )

    def state(self, task_id: str):
        with self._lock:
            entry = self._tasks.get(task_id)
        return entry[2] if entry else None

    def end_task(self, task_id: str, outcome: TaskState, *, broker) -> int:
        """The contract the orchestrator must follow: revoke every lease of the task FIRST,
        verify none is live, and only then mark the task finished (spec 5.2, T-07)."""
        if outcome in (TaskState.RUNNING, TaskState.ENDING):
            raise ValueError("outcome must be a terminal state")
        with self._lock:  # 1. stop new leases: the task is no longer live
            if task_id in self._tasks:
                self._tasks[task_id][2] = TaskState.ENDING
        revoked = broker.revoke_task(
            task_id, reason_code=_END_REASON[outcome]
        )  # 2. revoke everything
        if broker.live_lease_count(task_id) != 0:  # 3. verify, then 4. mark finished
            raise RuntimeError(
                "task still holds a live lease; refusing to mark it finished"
            )
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id][2] = outcome
        return revoked
