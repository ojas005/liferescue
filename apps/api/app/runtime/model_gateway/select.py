"""Config-driven provider selection (AI_PROVIDER=mock|nebius)."""

from __future__ import annotations

import os
from collections.abc import Mapping

from contract.interfaces import assert_model_adapter_allowed
from contract.workflow_definition import WorkflowDefinition

from .base import AIProvider
from .mock import MockAIProvider
from .nebius import NebiusProvider


def provider_from_env(
    env: Mapping[str, str] | None = None, *, workflow: WorkflowDefinition | None = None
) -> AIProvider:
    """AI_PROVIDER=mock|nebius (fallback: contract's LIFERESCUE_MODEL_ADAPTER; default 'nebius').

    The contract guard rejects 'mock' unless LIFERESCUE_ENV is a non-production value; the contract
    default for LIFERESCUE_ENV is 'production', so local dev must set LIFERESCUE_ENV=development.
    NebiusProvider construction never fails for a missing key: it raises NotConfigured at first use.
    """
    e = os.environ if env is None else env
    kind = (e.get("AI_PROVIDER") or e.get("LIFERESCUE_MODEL_ADAPTER") or "nebius").lower()
    assert_model_adapter_allowed(e.get("LIFERESCUE_ENV", "production"), kind)
    if kind == "mock":
        return MockAIProvider(workflow=workflow)
    return NebiusProvider(env=e)
