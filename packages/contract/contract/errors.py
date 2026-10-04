"""Contract exceptions. Runtime code raises these; the API layer maps them to ErrorResponse."""
from __future__ import annotations


class ContractError(Exception):
    code = "contract_error"


class IllegalTransition(ContractError):
    code = "illegal_transition"


class GuardFailed(ContractError):
    code = "guard_failed"


class WorkflowNotFound(ContractError):
    code = "workflow_not_found"


class RunNotFound(ContractError):
    code = "run_not_found"


class ApprovalError(ContractError):
    code = "approval_error"


class PolicyDenied(ContractError):
    code = "policy_denied"


class ToolError(ContractError):
    code = "tool_error"


class ModelUnavailable(ContractError):
    code = "model_unavailable"


class ModelSchemaError(ContractError):
    code = "model_schema_error"


class ConfigError(ContractError):
    code = "config_error"


class ConcurrentModification(ContractError):
    code = "concurrent_modification"
