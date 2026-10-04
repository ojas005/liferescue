"""The bundle of ports LR 04 owns, handed to the runtime wiring (app.runtime.wiring.build_engine, LR 06)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from contract.interfaces import ApprovalService, AuditLog, PolicyEngine, RunStore, WorkflowRegistry

from app.security.keys import Redactor
from app.settings import Settings


@dataclass(frozen=True)
class Ports:
    settings: Settings
    registry: WorkflowRegistry
    store: RunStore
    audit: AuditLog
    approvals: ApprovalService
    policy: PolicyEngine
    redactor: Redactor
    clock: Callable[[], datetime]
