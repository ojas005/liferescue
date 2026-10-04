"""Workflow variants built from the contract's vehicle_breakdown fixture (data only, no logic)."""

from __future__ import annotations

from typing import Any

from contract.fixtures.vehicle_breakdown import vehicle_breakdown
from contract.workflow_definition import WorkflowDefinition


def vehicle_variant(**edit: Any) -> WorkflowDefinition:
    """vehicle_breakdown() with edits applied to its dict form, re-validated by the contract (so illegal variants raise)."""
    d = vehicle_breakdown().model_dump(mode="json")
    for key, fn in edit.items():
        d[key] = fn(d[key]) if callable(fn) else fn
    return WorkflowDefinition(**d)


def without_policy_rule(rule_id: str) -> WorkflowDefinition:
    return vehicle_variant(policy=lambda p: {**p, "rules": [r for r in p["rules"] if r["rule_id"] != rule_id]})


def with_policy_rule(rule: dict[str, Any], first: bool = True) -> WorkflowDefinition:
    return vehicle_variant(policy=lambda p: {**p, "rules": ([rule] + p["rules"]) if first else (p["rules"] + [rule])})


def with_read_tool(name: str, action_type: str) -> WorkflowDefinition:
    """vehicle_breakdown plus an extra READ tool binding and an allowed action type (read-ok rule already matches READ)."""
    wf = vehicle_variant(
        tools=lambda t: t + [{"tool": name, "side_effect": "read"}],
        planning=lambda p: {**p, "allowed_action_types": p["allowed_action_types"] + [action_type]},
    )
    return wf
