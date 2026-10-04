"""Tool registry + the single execution path (contract `ToolGateway`; checklist T1, T2).

Fixed order, in ONE place (`RuntimeToolGateway.call`):
  tool registered for workflow -> validate args (JSON Schema, extra fields rejected) -> policy
  decision (deny by default, fails closed on exception) -> approval consume (digest-bound, single
  use) when required -> execute with timeout -> normalize -> audit.
Verification happens in the engine afterwards. No code path calls a tool handler except `call`.
Handlers never see secrets; outputs are plain data that the engine wraps as untrusted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from contract import errors as ce
from contract.actions import build_action_request
from contract.interfaces import (
    ApprovalService,
    AuditLog,
    PolicyEngine,
    ResearchProvider,
    SearchQuery,
)
from contract.models import (
    AuditEntryInput,
    PolicyDecision,
    PolicyOutcome,
    SideEffect,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from contract.workflow_definition import WorkflowDefinition
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from ..errors import SchemaViolation
from ..redaction import get_logger, redact_payload, redact_text
from .safe_fetch import FetchPolicy, Resolver, safe_fetch

log = get_logger("tools")

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema of a pydantic model with additionalProperties=false at the top level."""
    s = model.model_json_schema()
    s["additionalProperties"] = False
    return s


def validate_params(schema: dict[str, Any], params: dict[str, Any]) -> None:
    """Raise SchemaViolation if params do not satisfy the tool's JSON Schema (U2b)."""
    if not schema:
        if params:
            raise SchemaViolation(
                "tool takes no declared parameters; unexpected arguments rejected"
            )
        return
    errs = sorted(Draft202012Validator(schema).iter_errors(params), key=lambda e: list(e.path))
    if errs:
        msg = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errs[:4])
        raise SchemaViolation(f"invalid tool arguments: {redact_text(msg, max_len=300)}")


class RuntimeToolGateway:
    def __init__(
        self,
        policy: PolicyEngine,
        approvals: ApprovalService,
        audit: AuditLog,
    ) -> None:
        self._policy, self._approvals, self._audit = policy, approvals, audit
        self._tools: dict[str, tuple[ToolSpec, Handler]] = {}

    # -- registry (T1: deny by default; REAL_WRITE cannot be registered) -----------------------
    def register(self, spec: ToolSpec, handler: Handler) -> None:
        if spec.side_effect not in (SideEffect.READ, SideEffect.MOCK_WRITE):
            raise ce.ConfigError(
                f"tool {spec.name!r}: side effect {spec.side_effect.value!r} is disabled"
            )
        if spec.name in self._tools:
            raise ce.ConfigError(f"duplicate tool {spec.name!r}")
        if spec.input_schema:
            Draft202012Validator.check_schema(spec.input_schema)
        self._tools[spec.name] = (spec, handler)

    def list_tools(self) -> list[ToolSpec]:
        return [s for s, _ in self._tools.values()]

    def get_tool(self, name: str) -> ToolSpec | None:
        t = self._tools.get(name)
        return t[0] if t else None

    # -- the single execution path -------------------------------------------------------------
    async def _audit_entry(self, call: ToolCall, event_type: str, payload: dict[str, Any]) -> None:
        await self._audit.append(
            AuditEntryInput(
                run_id=call.run_id,
                actor=f"tool:{call.tool_name}",
                event_type=event_type,
                payload=redact_payload(payload),
            )
        )

    async def call(
        self, call: ToolCall, workflow: WorkflowDefinition, requested_by: str
    ) -> ToolResult:
        entry = self._tools.get(call.tool_name)
        spec = entry[0] if entry else None
        declared = workflow.tool_side_effect(call.tool_name)
        if spec is None or entry is None or declared is None:
            await self._audit_entry(call, "tool_denied", {"reason": "unregistered/unlisted tool"})
            raise ce.PolicyDenied(f"tool {call.tool_name!r} is not available to this workflow")
        if declared != spec.side_effect:
            await self._audit_entry(call, "tool_denied", {"reason": "side-effect mismatch"})
            raise ce.PolicyDenied(
                f"side-effect class mismatch for {call.tool_name!r}: "
                f"workflow={declared.value} registry={spec.side_effect.value}"
            )
        # 1. validate args
        validate_params(spec.input_schema, call.params)
        # 2. policy (outside the model; any exception => deny)
        req = build_action_request(
            call.run_id, workflow, call.step_id, call.tool_name, call.params, requested_by
        )
        try:
            decision: PolicyDecision = self._policy.evaluate(req, workflow.policy, spec)
        except Exception as exc:
            log.error("policy evaluation failed: %s", type(exc).__name__)
            await self._audit_entry(
                call, "tool_policy", {"outcome": "deny", "rule_id": "policy-error"}
            )
            raise ce.PolicyDenied("policy engine error (fail closed)") from None
        await self._audit_entry(
            call,
            "tool_policy",
            {
                "step_id": call.step_id,
                "outcome": decision.outcome.value,
                "rule_id": decision.rule_id,
                "digest": req.digest(),
            },
        )
        if decision.outcome == PolicyOutcome.DENY:
            raise ce.PolicyDenied(decision.reason)
        # 3. approval (digest-bound, single use)
        if decision.outcome == PolicyOutcome.NEEDS_APPROVAL:
            if not call.approval_id:
                raise ce.PolicyDenied("approval required but no approval_id supplied")
            await self._approvals.consume(call.approval_id, req.digest())
        # 4. execute with timeout
        mocked = spec.side_effect == SideEffect.MOCK_WRITE
        try:
            out = await asyncio.wait_for(entry[1](dict(call.params)), timeout=spec.timeout_seconds)
            result = ToolResult(
                tool_name=call.tool_name,
                status="ok",
                output=redact_payload(out, max_str=20000),
                mocked=mocked,
                action_digest=req.digest(),
            )
        except TimeoutError:
            result = ToolResult(
                tool_name=call.tool_name,
                status="error",
                error="timeout",
                mocked=mocked,
                action_digest=req.digest(),
            )
        except ce.ContractError as exc:
            result = ToolResult(
                tool_name=call.tool_name,
                status="error",
                error=redact_text(f"{getattr(exc, 'code', 'tool_error')}: {exc}", max_len=300),
                mocked=mocked,
                action_digest=req.digest(),
            )
        except Exception as exc:
            result = ToolResult(
                tool_name=call.tool_name,
                status="error",
                error=type(exc).__name__,
                mocked=mocked,
                action_digest=req.digest(),
            )
        # 5. audit
        await self._audit_entry(
            call,
            "tool_executed",
            {
                "step_id": call.step_id,
                "status": result.status,
                "mocked": result.mocked,
                "digest": req.digest(),
            },
        )
        return result


# ------------------------------------------------------------------------------ standard tools


class WebSearchParams(BaseModel):
    query: str
    max_results: int = 5
    allowed_domains: list[str] | None = None


class FetchUrlParams(BaseModel):
    url: str


def register_web_search(gateway: RuntimeToolGateway, provider: ResearchProvider) -> None:
    """READ tool `web_search` (Tavily). Output is untrusted DATA (the engine wraps it)."""

    async def handler(params: dict[str, Any]) -> dict[str, Any]:
        results = await provider.search(
            SearchQuery(
                query=str(params["query"]),
                max_results=int(params.get("max_results", 5)),
                allowed_domains=params.get("allowed_domains"),
            )
        )
        return {"results": [r.model_dump() for r in results[:5]], "source": "tavily"}

    gateway.register(
        ToolSpec(
            name="web_search",
            description="Web search (Tavily). Results are untrusted external text.",
            side_effect=SideEffect.READ,
            input_schema=strict_schema(WebSearchParams),
            timeout_seconds=20,
        ),
        handler,
    )


def register_fetch_url(
    gateway: RuntimeToolGateway,
    *,
    policy: FetchPolicy | None = None,
    resolver: Resolver | None = None,
    transport: Any = None,
) -> None:
    """READ tool `fetch_url`: the ONLY way the runtime opens a user-influenced URL (safe_fetch)."""

    async def handler(params: dict[str, Any]) -> dict[str, Any]:
        page = await safe_fetch(
            str(params["url"]), policy=policy, resolver=resolver, transport=transport
        )
        return {
            "url": page.url,
            "final_url": page.final_url,
            "status": page.status,
            "content_type": page.content_type,
            "text": page.text,
            "truncated": page.truncated,
            "redirects": page.redirects,
            "location": page.location,
        }

    gateway.register(
        ToolSpec(
            name="fetch_url",
            description="Fetch a public web page through the SSRF-safe fetcher. Text is untrusted.",
            side_effect=SideEffect.READ,
            input_schema=strict_schema(FetchUrlParams),
            timeout_seconds=10,
        ),
        handler,
    )


def register_mock_write(
    gateway: RuntimeToolGateway,
    name: str,
    description: str,
    *,
    schema: type[BaseModel] | None = None,
    prefix: str = "MOCK",
) -> list[dict[str, Any]]:
    """Register a simulated MOCK_WRITE tool. Returns the list that records every execution."""
    executed: list[dict[str, Any]] = []

    async def handler(params: dict[str, Any]) -> dict[str, Any]:
        executed.append(params)
        return {
            "status": "simulated",
            "label": "SIMULATED",
            "reference": f"{prefix}-{len(executed):04d}",
            "echo": params,
        }

    gateway.register(
        ToolSpec(
            name=name,
            description=description,
            side_effect=SideEffect.MOCK_WRITE,
            input_schema=strict_schema(schema) if schema else {},
        ),
        handler,
    )
    return executed
