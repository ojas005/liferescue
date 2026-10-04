"""ApprovalService (contract.interfaces.ApprovalService) on SQL: digest-bound, single use, TTL.

Every state change is ONE conditional UPDATE (compare-and-set on status, digest and expiry), so two concurrent
callers cannot both consume or both decide an approval, and a replayed/forged call affects zero rows (T4, T5).
There is no way to create an approval from model output: ``create`` is called only by the engine after a policy
decision of NEEDS_APPROVAL whose action_digest equals the request's digest."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from contract.errors import ApprovalError
from contract.models import (
    ActionRequest,
    Approval,
    ApprovalStatus,
    PolicyDecision,
    PolicyOutcome,
    utcnow,
)
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ApprovalRow
from app.security.keys import Redactor
from app.security.payloads import clean_text

S = ApprovalStatus
_LIVE = (S.PENDING.value, S.APPROVED.value)
MAX_TTL_SECONDS = 86400


def _to_model(r: ApprovalRow) -> Approval:
    return Approval(
        approval_id=str(r.id),
        run_id=str(r.run_id),
        step_id=r.step_id,
        bound_digest=r.bound_digest,
        status=ApprovalStatus(r.status),
        risk=r.risk,
        summary=r.summary,
        policy_version=r.policy_version,
        requested_at=r.requested_at,
        expires_at=r.expires_at,
        decided_by=r.decided_by,
        decided_at=r.decided_at,
        reason=r.reason,
    )


def _uuid(v: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(v)
    except (ValueError, AttributeError, TypeError):
        return None


class SqlApprovalService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        redactor: Redactor,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sf = session_factory
        self._redactor = redactor
        self._clock = clock

    def _expire(self, s: Session, where: list[object]) -> None:
        s.execute(
            update(ApprovalRow)
            .where(*where, ApprovalRow.status.in_(_LIVE), ApprovalRow.expires_at <= self._clock())  # type: ignore[arg-type]
            .values(status=S.EXPIRED.value)
        )

    async def create(
        self, request: ActionRequest, decision: PolicyDecision, summary: str, ttl_seconds: int
    ) -> Approval:
        if decision.outcome != PolicyOutcome.NEEDS_APPROVAL:
            raise ApprovalError("approvals can only be created for a NEEDS_APPROVAL policy decision")
        if decision.action_digest != request.digest() or decision.step_id != request.step_id:
            raise ApprovalError("policy decision does not match the requested action")
        if not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
            raise ApprovalError("invalid approval ttl")
        rid = _uuid(request.run_id)
        if rid is None:
            raise ApprovalError("invalid run id")
        now = self._clock()
        row = ApprovalRow(
            id=uuid.uuid4(),
            run_id=rid,
            step_id=request.step_id,
            bound_digest=request.digest(),
            status=S.PENDING.value,
            risk=decision.risk.value,
            summary=clean_text(self._redactor, summary[:2000]) or "",
            policy_version=decision.policy_version,
            requested_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        with self._sf() as s, s.begin():
            s.add(row)
            s.flush()
            return _to_model(row)

    async def get(self, approval_id: str) -> Approval | None:
        aid = _uuid(approval_id)
        if aid is None:
            return None
        with self._sf() as s, s.begin():
            self._expire(s, [ApprovalRow.id == aid])
            r = s.get(ApprovalRow, aid)
            return _to_model(r) if r else None

    async def list_for_run(self, run_id: str) -> list[Approval]:
        rid = _uuid(run_id)
        if rid is None:
            return []
        with self._sf() as s, s.begin():
            self._expire(s, [ApprovalRow.run_id == rid])
            rows = s.execute(
                select(ApprovalRow).where(ApprovalRow.run_id == rid).order_by(ApprovalRow.requested_at)
            ).scalars()
            return [_to_model(r) for r in rows]

    async def decide(
        self, approval_id: str, approve: bool, decided_by: str, reason: str | None = None
    ) -> Approval:
        aid = _uuid(approval_id)
        if aid is None:
            raise ApprovalError("unknown approval")
        now = self._clock()
        with self._sf() as s, s.begin():
            self._expire(s, [ApprovalRow.id == aid])
            res = s.execute(
                update(ApprovalRow)
                .where(
                    ApprovalRow.id == aid, ApprovalRow.status == S.PENDING.value, ApprovalRow.expires_at > now
                )
                .values(
                    status=S.APPROVED.value if approve else S.DENIED.value,
                    decided_by=decided_by,
                    decided_at=now,
                    reason=clean_text(self._redactor, reason[:500] if reason else None),
                )
            )
            r = s.get(ApprovalRow, aid)
            if r is None:
                raise ApprovalError("unknown approval")
            if res.rowcount != 1:  # type: ignore[attr-defined]
                raise ApprovalError(f"approval is {r.status}, not pending")
            s.refresh(r)
            return _to_model(r)

    async def revoke_pending(self, run_id: str) -> list[Approval]:
        rid = _uuid(run_id)
        if rid is None:
            return []
        with self._sf() as s, s.begin():
            self._expire(s, [ApprovalRow.run_id == rid])
            ids = list(
                s.execute(
                    select(ApprovalRow.id).where(ApprovalRow.run_id == rid, ApprovalRow.status.in_(_LIVE))
                ).scalars()
            )
            if not ids:
                return []
            s.execute(update(ApprovalRow).where(ApprovalRow.id.in_(ids)).values(status=S.REVOKED.value))
            return [
                _to_model(r) for r in s.execute(select(ApprovalRow).where(ApprovalRow.id.in_(ids))).scalars()
            ]

    async def consume(self, approval_id: str, expected_digest: str) -> Approval:
        aid = _uuid(approval_id)
        if aid is None:
            raise ApprovalError("unknown approval")
        now = self._clock()
        with self._sf() as s, s.begin():
            self._expire(s, [ApprovalRow.id == aid])
            res = s.execute(
                update(ApprovalRow)
                .where(
                    ApprovalRow.id == aid,
                    ApprovalRow.status == S.APPROVED.value,
                    ApprovalRow.bound_digest == expected_digest,
                    ApprovalRow.expires_at > now,
                )
                .values(status=S.CONSUMED.value)
            )
            r = s.get(ApprovalRow, aid)
            if r is None:
                raise ApprovalError("unknown approval")
            if res.rowcount != 1:  # type: ignore[attr-defined]
                if r.status == S.APPROVED.value and r.bound_digest != expected_digest:
                    raise ApprovalError("approval is bound to a different action digest")
                raise ApprovalError(
                    f"approval is {r.status}, not approved"
                )  # includes consumed => single use
            s.refresh(r)
            return _to_model(r)
