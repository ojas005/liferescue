from __future__ import annotations

from typing import Annotated

from contract.api_models import WorkflowSummary
from fastapi import APIRouter, Depends

from app.api.deps import Container, get_container

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get(
    "", response_model=list[WorkflowSummary], operation_id="listWorkflows", summary="List available workflows"
)
def list_workflows(c: Annotated[Container, Depends(get_container)]) -> list[WorkflowSummary]:
    return [
        WorkflowSummary(
            workflow_id=d.workflow_id,
            version=d.version,
            title=d.title,
            description=d.description,
            input_schema=d.intent.input_schema,
        )
        for d in c.ports.registry.list()
    ]
