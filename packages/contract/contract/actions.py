"""Helpers shared by engine and ToolGateway so both compute the SAME action digest."""
from __future__ import annotations

from typing import Any

from .models import ActionRequest, PlanStep
from .workflow_definition import WorkflowDefinition


def build_action_request(
    run_id: str, wf: WorkflowDefinition, step_id: str, tool_name: str, params: dict[str, Any], requested_by: str,
) -> ActionRequest:
    return ActionRequest(
        run_id=run_id, workflow_id=wf.workflow_id, workflow_version=wf.version, step_id=step_id, tool_name=tool_name,
        params=params, policy_version=wf.policy.version(), requested_by=requested_by,
    )


def action_for_step(run_id: str, wf: WorkflowDefinition, step: PlanStep, requested_by: str) -> ActionRequest:
    return build_action_request(run_id, wf, step.step_id, step.tool_name, step.params, requested_by)
