from __future__ import annotations

from typing import Annotated

from contract import CONTRACT_VERSION
from contract.api_models import HealthResponse
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import Container, get_container
from app.db.session import get_db

router = APIRouter()


class ReadyOut(BaseModel):
    status: str
    checks: dict[str, str]


@router.get(
    "/api/health",
    response_model=HealthResponse,
    operation_id="health",
    summary="Liveness and contract/model-adapter info (PROPOSED ASSUMPTION)",
)
def health(c: Annotated[Container, Depends(get_container)]) -> HealthResponse:
    return HealthResponse(
        status="ok", contract_version=CONTRACT_VERSION, model_adapter=c.settings.model_adapter
    )


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False, response_model=ReadyOut)
def readyz(response: Response, db: Annotated[Session, Depends(get_db)]) -> ReadyOut:
    try:
        db.execute(text("SELECT 1"))
        return ReadyOut(status="ready", checks={"database": "ok"})
    except Exception:  # noqa: BLE001 - never leak driver errors (they can contain DSNs)
        response.status_code = 503
        return ReadyOut(status="not_ready", checks={"database": "error"})
