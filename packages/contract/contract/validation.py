"""Helpers any runtime must use: run-input validation and startup check of workflow vs. tool registry."""
from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

from .errors import ConfigError, ContractError
from .interfaces import ToolGateway
from .workflow_definition import WorkflowDefinition


class InvalidInput(ContractError):
    pass


def validate_input(wf: WorkflowDefinition, data: dict[str, Any]) -> None:
    """Validate POST /api/runs `input` against the workflow's intent.input_schema (JSON Schema 2020-12)."""
    errors = sorted(Draft202012Validator(wf.intent.input_schema).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        raise InvalidInput("; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors[:5]))


def check_workflow_schemas(wf: WorkflowDefinition) -> None:
    """Fail fast at startup if a definition carries an invalid JSON Schema."""
    for name, schema in (("intent.input_schema", wf.intent.input_schema), ("intent.entities_schema", wf.intent.entities_schema)):
        if schema is not None:
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as e:  # noqa: BLE001
                raise ConfigError(f"{wf.workflow_id}: {name} is not a valid JSON Schema: {e}") from e


def validate_workflow_against_tools(wf: WorkflowDefinition, tools: ToolGateway) -> None:
    """Startup check: every tool a workflow binds exists in the ToolGateway with the SAME side-effect class."""
    for b in wf.tools:
        spec = tools.get_tool(b.tool)
        if spec is None:
            raise ConfigError(f"{wf.workflow_id}: tool '{b.tool}' is not registered in the ToolGateway")
        if spec.side_effect != b.side_effect:
            raise ConfigError(f"{wf.workflow_id}: tool '{b.tool}' side-effect mismatch (workflow={b.side_effect.value}, registry={spec.side_effect.value})")
    check_workflow_schemas(wf)
