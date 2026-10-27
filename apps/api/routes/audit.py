"""Audit inspection endpoints (Section 15)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from apps.api.dependencies import get_db
from packages.domain.models import AuditEvent
from packages.storage.sqlite_repo import SQLiteDatabase

router = APIRouter(prefix="/audit", tags=["Audit & Governance"])


@router.get("/events", response_model=list[AuditEvent])
def list_audit_events(
    db: Annotated[SQLiteDatabase, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
    incident_id: str | None = Query(default=None),
) -> list[AuditEvent]:
    """Retrieve append-only structured audit records (UPDATE/DELETE blocked by DB triggers)."""
    return db.list_audit(limit=limit, incident_id=incident_id)
