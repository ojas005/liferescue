"""FakeResearchProvider (Tavily stand-in) and FakeToolGateway (registry + the single execution path)."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from ..actions import build_action_request
from ..errors import PolicyDenied, ToolError
from ..interfaces import ApprovalService, AuditLog, PolicyEngine, ResearchProvider, SearchQuery, SearchResult
from ..models import (
    AuditEntryInput, PolicyOutcome, SideEffect, ToolCall, ToolResult, ToolSpec,
)
from ..workflow_definition import WorkflowDefinition

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class FakeResearchProvider:
    """Canned results; implements ResearchProvider. The real one wraps Tavily and lives in apps/api."""

    def __init__(self) -> None:
        self.queries: list[SearchQuery] = []

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        self.queries.append(query)
        return [SearchResult(title=f"Result {i} for {query.query}", url=f"https://example.test/{i}", snippet="canned snippet", score=1.0 - i / 10)
                for i in range(1, min(query.max_results, 2) + 1)]


class FakeToolGateway:
    def __init__(self, policy: PolicyEngine, approvals: ApprovalService, audit: AuditLog, research: ResearchProvider | None = None) -> None:
        self._policy, self._approvals, self._audit = policy, approvals, audit
        self._research = research or FakeResearchProvider()
        self._tools: dict[str, tuple[ToolSpec, Handler]] = {}
        self.executed: list[ToolCall] = []
        self._counter = 0
        self.register(ToolSpec(name="web_search", description="Web search (Tavily)", side_effect=SideEffect.READ), self._web_search)
        self.register(ToolSpec(name="dispatch_tow", description="Dispatch a tow truck (simulated)", side_effect=SideEffect.MOCK_WRITE), self._mock_ref("TOW"))
        self.register(ToolSpec(name="send_message", description="Send a message (simulated)", side_effect=SideEffect.MOCK_WRITE), self._mock_ref("MSG"))

    # registry
    def register(self, spec: ToolSpec, handler: Handler) -> None:
        self._tools[spec.name] = (spec, handler)

    def list_tools(self) -> list[ToolSpec]:
        return [s for s, _ in self._tools.values()]

    def get_tool(self, name: str) -> ToolSpec | None:
        t = self._tools.get(name)
        return t[0] if t else None

    async def _web_search(self, params: dict[str, Any]) -> dict[str, Any]:
        res = await self._research.search(SearchQuery(query=str(params["query"]), max_results=int(params.get("max_results", 5)),
                                                      allowed_domains=params.get("allowed_domains")))
        return {"results": [r.model_dump() for r in res]}

    def _mock_ref(self, prefix: str) -> Handler:
        async def handler(params: dict[str, Any]) -> dict[str, Any]:
            self._counter += 1
            return {"status": "simulated", "reference": f"MOCK-{prefix}-{self._counter:04d}", "echo": params}
        return handler

    async def call(self, call: ToolCall, workflow: WorkflowDefinition, requested_by: str) -> ToolResult:
        entry = self._tools.get(call.tool_name)
        spec = entry[0] if entry else None
        declared = workflow.tool_side_effect(call.tool_name)
        if spec is None or declared is None:
            raise ToolError(f"tool '{call.tool_name}' is not registered for workflow '{workflow.workflow_id}'")
        if declared != spec.side_effect:
            raise PolicyDenied(f"side-effect class mismatch for '{call.tool_name}': workflow={declared.value} registry={spec.side_effect.value}")
        req = build_action_request(call.run_id, workflow, call.step_id, call.tool_name, call.params, requested_by)
        decision = self._policy.evaluate(req, workflow.policy, spec)
        await self._audit.append(AuditEntryInput(run_id=call.run_id, actor=f"tool:{call.tool_name}", event_type="tool_policy",
                                                 payload={"step_id": call.step_id, "outcome": decision.outcome.value, "rule_id": decision.rule_id,
                                                          "digest": req.digest()}))
        if decision.outcome == PolicyOutcome.DENY:
            raise PolicyDenied(decision.reason)
        if decision.outcome == PolicyOutcome.NEEDS_APPROVAL:
            if not call.approval_id:
                raise PolicyDenied("approval required but no approval_id supplied")
            await self._approvals.consume(call.approval_id, req.digest())  # raises ApprovalError (single use, digest-bound)
        try:
            out = await asyncio.wait_for(entry[1](call.params), timeout=spec.timeout_seconds)  # type: ignore[index]
            result = ToolResult(tool_name=call.tool_name, status="ok", output=out, mocked=spec.side_effect == SideEffect.MOCK_WRITE,
                                action_digest=req.digest())
        except Exception as e:  # noqa: BLE001 - adapter errors become error results, never leak raw traces
            result = ToolResult(tool_name=call.tool_name, status="error", error=f"{type(e).__name__}", mocked=spec.side_effect == SideEffect.MOCK_WRITE,
                                action_digest=req.digest())
        self.executed.append(call)
        await self._audit.append(AuditEntryInput(run_id=call.run_id, actor=f"tool:{call.tool_name}", event_type="tool_executed",
                                                 payload={"step_id": call.step_id, "status": result.status, "mocked": result.mocked,
                                                          "digest": req.digest()}))
        return result
