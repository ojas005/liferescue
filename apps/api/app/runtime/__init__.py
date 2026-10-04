"""LifeRescue agent runtime (pure Python; importable without FastAPI or a database).

`WorkflowEngine` implements `contract.interfaces.RunEngine`. See README.md.
"""

from .engine import RunLimits, WorkflowEngine
from .errors import FetchFailed, LimitReached, NotConfigured, SchemaViolation, SSRFBlocked
from .events import EventSink, InMemoryEventSink
from .memory import InMemoryMemory, Memory, MemoryScope

__all__ = [
    "EventSink",
    "FetchFailed",
    "InMemoryEventSink",
    "InMemoryMemory",
    "LimitReached",
    "Memory",
    "MemoryScope",
    "NotConfigured",
    "RunLimits",
    "SSRFBlocked",
    "SchemaViolation",
    "WorkflowEngine",
]
