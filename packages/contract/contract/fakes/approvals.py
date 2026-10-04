"""In-memory ApprovalService: digest-bound, single use, TTL."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Callable

from ..errors import ApprovalError
from ..models import ActionRequest, Approval, ApprovalStatus, PolicyDecision, utcnow


class InMemoryApprovalService:
    def __init__(self, clock: Callable[[], datetime] = utcnow) -> None:
        self._clock = clock
        self._items: dict[str, Approval] = {}

    async def create(self, request: ActionRequest, decision: PolicyDecision, summary: str, ttl_seconds: int) -> Approval:
        now = self._clock()
        ap = Approval(approval_id=str(uuid.uuid4()), run_id=request.run_id, step_id=request.step_id, bound_digest=request.digest(),
                      risk=decision.risk, summary=summary, policy_version=decision.policy_version, requested_at=now,
                      expires_at=now + timedelta(seconds=ttl_seconds))
        self._items[ap.approval_id] = ap
        return ap

    async def get(self, approval_id: str) -> Approval | None:
        return self._refresh(self._items.get(approval_id))

    async def list_for_run(self, run_id: str) -> list[Approval]:
        return [a for a in (self._refresh(x) for x in self._items.values()) if a is not None and a.run_id == run_id]

    def _refresh(self, ap: Approval | None) -> Approval | None:
        if ap is not None and ap.status in (ApprovalStatus.PENDING, ApprovalStatus.APPROVED) and ap.expires_at <= self._clock():
            ap = ap.model_copy(update={"status": ApprovalStatus.EXPIRED})
            self._items[ap.approval_id] = ap
        return ap

    async def decide(self, approval_id: str, approve: bool, decided_by: str, reason: str | None = None) -> Approval:
        ap = self._refresh(self._items.get(approval_id))
        if ap is None:
            raise ApprovalError("unknown approval")
        if ap.status != ApprovalStatus.PENDING:
            raise ApprovalError(f"approval is {ap.status.value}, not pending")
        ap = ap.model_copy(update={"status": ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED,
                                   "decided_by": decided_by, "decided_at": self._clock(), "reason": reason})
        self._items[approval_id] = ap
        return ap

    async def revoke_pending(self, run_id: str) -> list[Approval]:
        out = []
        for ap in await self.list_for_run(run_id):
            if ap.status in (ApprovalStatus.PENDING, ApprovalStatus.APPROVED):
                ap = ap.model_copy(update={"status": ApprovalStatus.REVOKED})
                self._items[ap.approval_id] = ap
                out.append(ap)
        return out

    async def consume(self, approval_id: str, expected_digest: str) -> Approval:
        ap = self._refresh(self._items.get(approval_id))
        if ap is None:
            raise ApprovalError("unknown approval")
        if ap.status != ApprovalStatus.APPROVED:
            raise ApprovalError(f"approval is {ap.status.value}, not approved")  # includes CONSUMED => single use
        if ap.bound_digest != expected_digest:
            raise ApprovalError("approval is bound to a different action digest")
        ap = ap.model_copy(update={"status": ApprovalStatus.CONSUMED})
        self._items[approval_id] = ap
        return ap
