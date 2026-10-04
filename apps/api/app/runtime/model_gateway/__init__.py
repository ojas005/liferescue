"""Model gateway: the ONLY place LLM calls and LLM HTTP clients live (contract rules R2/R4)."""

from contract.interfaces import ModelGateway

from .base import (
    MOCK_LABEL,
    AIProvider,
    ModelBudget,
    ProviderBase,
    ProviderHealth,
    ProviderStats,
    extract_json,
)
from .mock import MockAIProvider, default_instance
from .nebius import NebiusProvider
from .select import provider_from_env

__all__ = [
    "MOCK_LABEL",
    "AIProvider",
    "MockAIProvider",
    "ModelBudget",
    "ModelGateway",
    "NebiusProvider",
    "ProviderBase",
    "ProviderHealth",
    "ProviderStats",
    "default_instance",
    "extract_json",
    "provider_from_env",
]
