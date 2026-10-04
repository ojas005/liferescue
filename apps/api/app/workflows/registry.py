"""Static WorkflowRegistry (contract.interfaces.WorkflowRegistry) over the definitions in this package."""

from __future__ import annotations

from contract.workflow_definition import WorkflowDefinition

from app.workflows.life_admin.definition import DEFINITION as LIFE_ADMIN
from app.workflows.scam_investigation.definition import DEFINITION as SCAM_INVESTIGATION
from app.workflows.vehicle_breakdown.definition import DEFINITION as VEHICLE_BREAKDOWN


class StaticWorkflowRegistry:
    def __init__(self, definitions: list[WorkflowDefinition]) -> None:
        self._defs = {(d.workflow_id, d.version): d for d in definitions}
        if len(self._defs) != len(definitions):
            raise ValueError("duplicate (workflow_id, version)")

    def list(self) -> list[WorkflowDefinition]:
        return sorted(self._defs.values(), key=lambda d: (d.workflow_id, d.version))

    def get(self, workflow_id: str, version: str | None = None) -> WorkflowDefinition | None:
        if version is not None:
            return self._defs.get((workflow_id, version))
        cands = [d for (wid, _), d in self._defs.items() if wid == workflow_id]
        return max(cands, key=lambda d: tuple(int(x) for x in d.version.split("."))) if cands else None


def default_definitions() -> list[WorkflowDefinition]:
    return [VEHICLE_BREAKDOWN, SCAM_INVESTIGATION, LIFE_ADMIN]
