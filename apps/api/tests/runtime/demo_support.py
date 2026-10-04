"""Test/dev-only demo workflow and stack builder (NOT product code; real definitions live in
app/workflows/<id>/definition.py). Uses contract fakes for LR 04's pieces (store/policy/approvals/
audit), which is allowed under tests/ (rule R3)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from contract.fakes import (
    FakeResearchProvider,
    InMemoryApprovalService,
    InMemoryAuditLog,
    InMemoryRunStore,
    InMemoryWorkflowRegistry,
    RulePolicyEngine,
)
from contract.models import PolicyOutcome, RiskLevel, SideEffect, utcnow
from contract.workflow_definition import (
    ApprovalRequirements,
    EvidenceRequirement,
    IntentSpec,
    PlanningRules,
    PolicyRule,
    PolicySpec,
    ResearchStrategy,
    ToolBinding,
    VerificationCheck,
    VerificationStrategy,
    WorkflowDefinition,
)
from pydantic import BaseModel

from app.runtime import InMemoryEventSink, InMemoryMemory, RunLimits, WorkflowEngine
from app.runtime.model_gateway import AIProvider, MockAIProvider
from app.runtime.tools import (
    RuntimeToolGateway,
    register_fetch_url,
    register_mock_write,
    register_web_search,
)
from app.verification import RuntimeVerifier

T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class NotifyParams(BaseModel):
    text: str = "hello"


def demo_definition(**overrides: Any) -> WorkflowDefinition:
    """Tiny generic workflow used by tests: read tools + one simulated notification."""
    data: dict[str, Any] = {
        "workflow_id": "demo_notify",
        "version": "0.1.0",
        "title": "Demo notify (tests only)",
        "description": "Exercises every pipeline stage.",
        "intent": IntentSpec(
            input_schema={
                "type": "object",
                "required": ["message"],
                "properties": {"message": {"type": "string", "minLength": 1, "maxLength": 20000}},
                "additionalProperties": False,
            },
            instructions="Extract the situation as structured data.",
        ),
        "evidence": [
            EvidenceRequirement(
                key="message",
                description="user message",
                source="user_input",
                input_field="message",
            ),
        ],
        "research": ResearchStrategy(
            enabled=True,
            tool="web_search",
            queries=["help with {category}"],
            max_results_per_query=3,
        ),
        "planning": PlanningRules(
            instructions="Propose the smallest plan using the listed tools.",
            max_steps=3,
            allowed_action_types=["notify", "lookup"],
        ),
        "tools": [
            ToolBinding(tool="web_search", side_effect=SideEffect.READ),
            ToolBinding(tool="fetch_url", side_effect=SideEffect.READ),
            ToolBinding(tool="demo_notify", side_effect=SideEffect.MOCK_WRITE),
        ],
        "policy": PolicySpec(
            rules=[
                PolicyRule(
                    rule_id="read-ok",
                    side_effect=SideEffect.READ,
                    outcome=PolicyOutcome.ALLOW,
                    risk=RiskLevel.LOW,
                    reason="read tools allowed",
                ),
                PolicyRule(
                    rule_id="notify-approval",
                    tool="demo_notify",
                    outcome=PolicyOutcome.NEEDS_APPROVAL,
                    risk=RiskLevel.MEDIUM,
                    reason="user must approve",
                ),
            ]
        ),
        "approvals": ApprovalRequirements(),
        "verification": VerificationStrategy(
            checks=[
                VerificationCheck(
                    check_id="notify-ok", kind="tool_result_status", tool="demo_notify"
                ),
                VerificationCheck(
                    check_id="has-message", kind="evidence_present", evidence_key="message"
                ),
            ]
        ),
    }
    data.update(overrides)
    return WorkflowDefinition(**data)


@dataclass
class Stack:
    engine: WorkflowEngine
    store: InMemoryRunStore
    approvals: InMemoryApprovalService
    audit: InMemoryAuditLog
    sink: InMemoryEventSink
    memory: InMemoryMemory
    gateway: RuntimeToolGateway
    verifier: RuntimeVerifier
    provider: AIProvider
    research: FakeResearchProvider
    notified: list[dict[str, Any]] = field(default_factory=list)
    definition: WorkflowDefinition | None = None


def build_stack(
    provider: AIProvider | None = None,
    definition: WorkflowDefinition | None = None,
    *,
    limits: RunLimits | None = None,
    clock: Callable[[], datetime] = utcnow,
    research: FakeResearchProvider | None = None,
    fetch_kwargs: dict[str, Any] | None = None,
) -> Stack:
    wf = definition or demo_definition()
    store, audit = InMemoryRunStore(), InMemoryAuditLog()
    approvals = InMemoryApprovalService(clock)
    policy = RulePolicyEngine()
    gateway = RuntimeToolGateway(policy, approvals, audit)
    research = research or FakeResearchProvider()
    register_web_search(gateway, research)
    register_fetch_url(gateway, **(fetch_kwargs or {}))
    notified = register_mock_write(
        gateway,
        "demo_notify",
        "Send a simulated notification",
        schema=NotifyParams,
        prefix="MOCK-NOTIFY",
    )
    prov = provider or MockAIProvider(workflow=wf)
    verifier = RuntimeVerifier(prov)
    sink, memory = InMemoryEventSink(), InMemoryMemory()
    engine = WorkflowEngine(
        registry=InMemoryWorkflowRegistry([wf]),
        store=store,
        provider=prov,
        tools=gateway,
        policy=policy,
        approvals=approvals,
        audit=audit,
        verifier=verifier,
        memory=memory,
        event_sink=sink,
        limits=limits,
        clock=clock,
    )
    return Stack(
        engine,
        store,
        approvals,
        audit,
        sink,
        memory,
        gateway,
        verifier,
        prov,
        research,
        notified,
        wf,
    )
