"""Test doubles for parallel development. NEVER imported by apps/api or apps/web production code paths."""
from .approvals import InMemoryApprovalService
from .audit import InMemoryAuditLog
from .engine import ReferenceRunEngine, build_fake_stack
from .memory import InMemoryRunStore, InMemoryWorkflowRegistry
from .mock_model import MockModel
from .policy import RulePolicyEngine
from .tools import FakeResearchProvider, FakeToolGateway
from .verifier import RuleVerifier

__all__ = ["InMemoryApprovalService", "InMemoryAuditLog", "ReferenceRunEngine", "build_fake_stack", "InMemoryRunStore",
           "InMemoryWorkflowRegistry", "MockModel", "RulePolicyEngine", "FakeResearchProvider", "FakeToolGateway", "RuleVerifier"]
