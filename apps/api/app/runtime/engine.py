"""WorkflowEngine: the ONE implementation of `contract.interfaces.RunEngine`.

Generic: no workflow-specific logic. Everything a workflow needs is in its `WorkflowDefinition`
(data). The engine only wires the contract ports (ModelGateway, ToolGateway, PolicyEngine,
ApprovalService, Verifier, AuditLog, RunStore) through the pipeline

  INTENT -> EVIDENCE -> RESEARCH -> PLAN -> POLICY -> APPROVAL -> ACTION -> VERIFICATION -> AUDIT

Guarantees (each covered by tests in apps/api/tests/runtime):
* `RunRecord.state` changes ONLY through `contract.run_state_machine.apply_transition`.
* Fail closed: any exception in a stage fails the run with a redacted reason (never a partial success).
* Pause/resume: the APPROVAL state blocks until every gated step has a human decision; `advance` is
  re-entrant and resumes from the persisted state; actions are recorded one by one and an
  already-consumed approval without a recorded result fails the run instead of re-executing.
* Untrusted data: user input, tool output and research are quoted as data blocks in USER messages
  (checklist U1/U3); model plans are validated deterministically against the workflow allowlist and
  tool schemas (U2); policy and approvals live in code, not prompts.
* Per-run caps (U5): <= 15 steps, <= 8 tool calls, <= 60 s active wall time per advance, token budget.
  Hitting a cap fails the run with reason `limit_reached: ...` (contract has no LIMIT_REACHED
  state; see README "contract change requests").
* Every event carries redacted payloads; model-derived events are stamped with the provider and a
  `mock` flag + label so mock output can never be mistaken for real AI.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from contract import CONTRACT_VERSION
from contract import errors as ce
from contract.actions import action_for_step
from contract.interfaces import (
    ApprovalService,
    AuditLog,
    PolicyEngine,
    RunStore,
    ToolGateway,
    Verifier,
    WorkflowRegistry,
)
from contract.models import (
    TERMINAL_STATES,
    ApprovalStatus,
    AuditEntryInput,
    EventType,
    Evidence,
    IntentResult,
    Message,
    PlanProposal,
    PlanStep,
    PolicyOutcome,
    RunRecord,
    RunState,
    SideEffect,
    ToolCall,
    ToolResult,
    canonical_json,
    sha256_hex,
    utcnow,
)
from contract.run_state_machine import TransitionContext, apply_transition
from contract.validation import validate_input, validate_workflow_against_tools
from contract.workflow_definition import WorkflowDefinition
from jsonschema import Draft202012Validator

from .errors import LimitReached, SchemaViolation
from .events import EventSink
from .memory import Memory, MemoryScope
from .model_gateway import AIProvider
from .redaction import get_logger, mask_pii, redact_payload, redact_text
from .tools.gateway import validate_params
from .untrusted import (
    MAX_RESULTS_PER_BLOCK,
    UNTRUSTED_PREAMBLE,
    new_boundary,
    wrap_untrusted,
)

log = get_logger("engine")
S = RunState


@dataclass(frozen=True)
class RunLimits:
    max_steps: int = 15
    max_tool_calls: int = 8
    max_seconds: float = 60.0
    max_tokens: int = 40_000
    max_research_queries: int = 5
    model_timeout_s: float = 30.0


class _Meter:
    def __init__(self) -> None:
        self.steps = 0
        self.tool_calls = 0
        self.tokens = 0
        self.research_queries = 0
        self.started = time.monotonic()


def _prompt_safe(text: str) -> str:
    """P2: nothing credential-shaped or card/OTP/ID-shaped goes into a model prompt."""
    return mask_pii(redact_text(text))


def _dotted(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


class WorkflowEngine:
    """Implements `contract.interfaces.RunEngine`."""

    def __init__(
        self,
        *,
        registry: WorkflowRegistry,
        store: RunStore,
        provider: AIProvider,
        tools: ToolGateway,
        policy: PolicyEngine,
        approvals: ApprovalService,
        audit: AuditLog,
        verifier: Verifier,
        memory: Memory | None = None,
        event_sink: EventSink | None = None,
        limits: RunLimits | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.registry, self.store, self.provider, self.tools = registry, store, provider, tools
        self.policy, self.approvals, self.audit, self.verifier = policy, approvals, audit, verifier
        self.memory, self.sink = memory, event_sink
        self.limits = limits or RunLimits()
        self.clock = clock
        self._meters: dict[str, _Meter] = {}
        self._boundaries: dict[str, str] = {}
        for wf in registry.list():  # fail fast at startup
            validate_workflow_against_tools(wf, tools)

    # ============================================================ RunEngine protocol
    async def start(
        self, workflow_id: str, input: dict[str, Any], workflow_version: str | None = None
    ) -> RunRecord:
        wf = self.registry.get(workflow_id, workflow_version)
        if wf is None:
            raise ce.WorkflowNotFound(workflow_id)
        validate_input(wf, input)
        now = self.clock()
        run = await self.store.create_run(
            RunRecord(
                run_id=str(uuid.uuid4()),
                workflow_id=wf.workflow_id,
                workflow_version=wf.version,
                contract_version=CONTRACT_VERSION,
                input=input,
                created_at=now,
                updated_at=now,
            )
        )
        await self._audit(
            run,
            "system",
            "run_created",
            {
                "workflow_id": wf.workflow_id,
                "workflow_version": wf.version,
                "provider": self._provider_info(),
            },
        )
        await self._emit(
            run,
            S.INTENT,
            EventType.STATE_CHANGE,
            {"to": "intent", "note": "run created", "provider": self._provider_info()},
        )
        return await self.advance(run.run_id)

    async def advance(self, run_id: str) -> RunRecord:
        run = await self._get(run_id)
        wf = self._wf(run)
        meter = await self._meter(run)
        meter.started = time.monotonic()  # wall-time cap applies per continuous advance segment
        while run.state not in TERMINAL_STATES:
            try:
                nxt = await self._step(run, wf)
            except (asyncio.CancelledError, ce.ConcurrentModification):
                raise
            except LimitReached as exc:
                run = await self._get(run_id)
                nxt = await self._fail(run, f"limit_reached: {exc}", code="limit_reached")
            except Exception as exc:
                run = await self._get(run_id)
                code = getattr(exc, "code", type(exc).__name__)
                reason = f"{code}: {redact_text(str(exc), max_len=200)}"
                log.warning("run %s failed in %s: %s", run_id, run.state.value, code)
                nxt = await self._fail(run, reason, code=str(code))
            if nxt is None:  # blocked on a human decision
                return await self._get(run_id)
            run = nxt
        return run

    async def decide_approval(
        self,
        run_id: str,
        approval_id: str,
        approve: bool,
        decided_by: str,
        reason: str | None = None,
    ) -> RunRecord:
        run = await self._get(run_id)
        if run.state != S.APPROVAL:
            raise ce.ApprovalError(f"run is in state {run.state.value}, not approval")
        ap = next(
            (a for a in await self.approvals.list_for_run(run_id) if a.approval_id == approval_id),
            None,
        )
        if ap is None:
            raise ce.ApprovalError("approval does not belong to this run")
        ap = await self.approvals.decide(approval_id, approve, decided_by, reason)
        await self._emit(
            run,
            S.APPROVAL,
            EventType.APPROVAL,
            {
                "approval_id": ap.approval_id,
                "step_id": ap.step_id,
                "status": ap.status.value,
                "decided_by": decided_by,
            },
        )
        await self._audit(
            run,
            f"user:{decided_by}",
            "approval_decided",
            {"approval_id": ap.approval_id, "status": ap.status.value, "digest": ap.bound_digest},
        )
        return await self.advance(run_id)

    async def cancel(self, run_id: str, requested_by: str, reason: str | None = None) -> RunRecord:
        run = await self._get(run_id)
        new = apply_transition(
            run,
            S.CANCELLED,
            TransitionContext(reason=reason or "cancelled by user", now=self.clock()),
        )
        await self.approvals.revoke_pending(run_id)
        return await self._commit(run, new, actor=f"user:{requested_by}")

    # ============================================================ plumbing
    def _wf(self, run: RunRecord) -> WorkflowDefinition:
        wf = self.registry.get(run.workflow_id, run.workflow_version)
        if wf is None:
            raise ce.WorkflowNotFound(f"{run.workflow_id}@{run.workflow_version}")
        return wf

    async def _get(self, run_id: str) -> RunRecord:
        run = await self.store.get_run(run_id)
        if run is None:
            raise ce.RunNotFound(run_id)
        return run

    def _provider_info(self) -> dict[str, Any]:
        return {
            "adapter": self.provider.adapter_kind,
            "model": self.provider.model_id,
            "label": self.provider.label,
            "mock": self.provider.adapter_kind == "mock",
        }

    async def _emit(
        self, run: RunRecord, step: RunState, type: EventType, payload: dict[str, Any]
    ) -> None:
        ev = await self.store.append_event(
            run.run_id, step, type, redact_payload(payload), self.clock()
        )
        if self.sink is not None:
            await self.sink.emit(ev)

    async def _audit(
        self, run: RunRecord, actor: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        await self.audit.append(
            AuditEntryInput(
                run_id=run.run_id,
                actor=actor,
                event_type=event_type,
                payload=redact_payload(payload),
            )
        )

    async def _commit(self, old: RunRecord, new: RunRecord, actor: str = "system") -> RunRecord:
        saved = await self.store.save_run(new, expected_version=old.version)
        await self._emit(
            saved,
            saved.state,
            EventType.STATE_CHANGE,
            {"from": old.state.value, "to": saved.state.value, "reason": saved.terminal_reason},
        )
        await self._audit(
            saved,
            actor,
            "state_change",
            {"from": old.state.value, "to": saved.state.value, "reason": saved.terminal_reason},
        )
        return saved

    async def _go(
        self, run: RunRecord, to: RunState, ctx: TransitionContext | None = None, **updates: Any
    ) -> RunRecord:
        """The only state-changing path: apply_transition -> compare-and-swap save."""
        base = run.model_copy(update=updates) if updates else run
        base = base.model_copy(update={"version": run.version})
        new = apply_transition(base, to, ctx or TransitionContext(now=self.clock()))
        return await self._commit(run, new)

    async def _save_progress(self, run: RunRecord, **updates: Any) -> RunRecord:
        """Persist non-state progress (e.g. one action result) with optimistic concurrency."""
        new = run.model_copy(
            update={**updates, "version": run.version + 1, "updated_at": self.clock()}
        )
        return await self.store.save_run(new, expected_version=run.version)

    async def _fail(self, run: RunRecord, reason: str, code: str = "failed") -> RunRecord:
        await self._emit(run, run.state, EventType.ERROR, {"reason": reason, "code": code})
        failed = await self._go(run, S.FAILED, TransitionContext(reason=reason, now=self.clock()))
        await self._write_memory(failed, outcome="failed")
        return failed

    # ------------------------------------------------------------ budgets (U5)
    async def _meter(self, run: RunRecord) -> _Meter:
        m = self._meters.get(run.run_id)
        if m is not None:
            return m
        m = _Meter()
        after = 0
        while True:  # rebuild durable counters after a restart
            evs = await self.store.list_events(run.run_id, after_seq=after, limit=200)
            for e in evs:
                after = max(after, e.seq)
                if e.type == EventType.STATE_CHANGE:
                    m.steps += 1
                if e.payload.get("tool_call"):
                    m.tool_calls += 1
                m.tokens += int(e.payload.get("tokens", 0) or 0)
            if len(evs) < 200:
                break
        self._meters[run.run_id] = m
        return m

    def _remaining_s(self, m: _Meter) -> float:
        return self.limits.max_seconds - (time.monotonic() - m.started)

    def _check_caps(self, m: _Meter) -> None:
        if m.steps >= self.limits.max_steps:
            raise LimitReached(f"step cap {self.limits.max_steps} reached")
        if self._remaining_s(m) <= 0:
            raise LimitReached(f"wall-time cap {self.limits.max_seconds:.0f}s reached")
        if m.tokens >= self.limits.max_tokens:
            raise LimitReached(f"token budget {self.limits.max_tokens} reached")

    async def _model(
        self,
        run: RunRecord,
        schema: type,
        messages: list[Message],
        purpose: str,
        max_tokens: int = 1024,
    ) -> Any:
        m = await self._meter(run)
        self._check_caps(m)
        res = await self.provider.complete_structured(
            schema,
            messages,
            purpose=purpose,
            run_id=run.run_id,
            max_tokens=max_tokens,
            timeout_s=max(1.0, min(self.limits.model_timeout_s, self._remaining_s(m))),
        )
        m.tokens += res.usage.input_tokens + res.usage.output_tokens
        return res

    async def _call_tool(
        self,
        run: RunRecord,
        wf: WorkflowDefinition,
        step_id: str,
        tool: str,
        params: dict[str, Any],
        approval_id: str | None = None,
    ) -> ToolResult:
        m = await self._meter(run)
        self._check_caps(m)
        if m.tool_calls >= self.limits.max_tool_calls:
            raise LimitReached(f"tool-call cap {self.limits.max_tool_calls} reached")
        m.tool_calls += 1
        try:
            return await self.tools.call(
                ToolCall(
                    run_id=run.run_id,
                    step_id=step_id,
                    tool_name=tool,
                    params=params,
                    approval_id=approval_id,
                ),
                wf,
                run.owner,
            )
        except (ce.PolicyDenied, SchemaViolation) as exc:
            await self._emit(
                run,
                run.state,
                EventType.POLICY,
                {
                    "step_id": step_id,
                    "tool": tool,
                    "outcome": "deny",
                    "reason": str(exc),
                    "tool_call": True,
                },
            )
            raise

    # ------------------------------------------------------------ stage dispatch
    async def _step(self, run: RunRecord, wf: WorkflowDefinition) -> RunRecord | None:
        m = await self._meter(run)
        self._check_caps(m)
        handler = {
            S.INTENT: self._intent,
            S.EVIDENCE: self._evidence,
            S.RESEARCH: self._research,
            S.PLAN: self._plan,
            S.POLICY: self._policy,
            S.APPROVAL: self._approval,
            S.ACTION: self._action,
            S.VERIFICATION: self._verification,
            S.AUDIT: self._audit_stage,
        }[run.state]
        m.steps += 1 if run.state != S.APPROVAL else 0
        return await handler(run, wf)  # type: ignore[no-any-return]

    def _boundary(self, run: RunRecord) -> str:
        return self._boundaries.setdefault(run.run_id, new_boundary())

    # ------------------------------------------------------------ stages
    async def _intent(self, run: RunRecord, wf: WorkflowDefinition) -> RunRecord:
        # P2: mask cards/OTP/Aadhaar/PAN and credential-shaped strings BEFORE the model call
        text = _prompt_safe(json.dumps(run.input, ensure_ascii=False))
        res = await self._model(
            run,
            IntentResult,
            [
                Message(
                    role="system", content=wf.intent.instructions + "\n\n" + UNTRUSTED_PREAMBLE
                ),
                Message(
                    role="user", content=wrap_untrusted("user_input", text, self._boundary(run))
                ),
            ],
            "intent",
        )
        # P2: never persist credential-shaped strings the model may have echoed
        intent = IntentResult.model_validate(redact_payload(res.output.model_dump(mode="json")))
        if wf.intent.entities_schema is not None:
            errs = list(
                Draft202012Validator(wf.intent.entities_schema).iter_errors(intent.entities)
            )
            if errs:
                raise SchemaViolation(f"intent entities invalid: {errs[0].message[:150]}")
        await self._emit(
            run,
            S.INTENT,
            EventType.INTENT,
            {
                "summary": intent.summary,
                "category": intent.category,
                "urgency": intent.urgency.value,
                "entities": intent.entities,
                "provider": self._provider_info(),
                "tokens": res.usage.input_tokens + res.usage.output_tokens,
                "latency_ms": res.usage.latency_ms,
            },
        )
        return await self._go(run, S.EVIDENCE, intent=intent)

    async def _add_evidence(
        self,
        run: RunRecord,
        key: str,
        kind: str,
        source: str,
        content: dict[str, Any],
        trust: str = "untrusted",
    ) -> None:
        await self.store.add_evidence(
            Evidence(
                evidence_id=str(uuid.uuid4()),
                run_id=run.run_id,
                key=key,
                kind=kind,  # type: ignore[arg-type]
                source=source,
                content=content,
                trust=trust,  # type: ignore[arg-type]
                retrieved_at=self.clock(),
                sha256=sha256_hex(canonical_json(content)),
            )
        )

    async def _evidence(self, run: RunRecord, wf: WorkflowDefinition) -> RunRecord:
        got: list[str] = []
        missing: list[str] = []
        for req in wf.evidence:
            content: dict[str, Any] | None = None
            source = "user"
            if req.source == "user_input":
                v = _dotted(run.input, req.input_field or "")
                content = {"value": v} if v not in (None, "") else None
            else:
                source = req.tool or ""
                r = await self._call_tool(
                    run,
                    wf,
                    f"evidence-{req.key}",
                    req.tool or "",
                    {"entities": run.intent.entities if run.intent else {}},
                )
                content = r.output if r.status == "ok" else None
                await self._emit(
                    run,
                    S.EVIDENCE,
                    EventType.EVIDENCE,
                    {
                        "step_id": f"evidence-{req.key}",
                        "tool": req.tool,
                        "status": r.status,
                        "tool_call": True,
                    },
                )
            if content is None:
                missing.append(req.key)
                if req.required:
                    await self._emit(
                        run, S.EVIDENCE, EventType.EVIDENCE, {"collected": got, "missing": missing}
                    )
                    raise ce.GuardFailed(f"required evidence '{req.key}' is missing")
                continue
            await self._add_evidence(
                run,
                req.key,
                "user_input" if req.source == "user_input" else "tool_result",
                source,
                content,
            )
            got.append(req.key)
        await self._emit(
            run, S.EVIDENCE, EventType.EVIDENCE, {"collected": got, "missing": missing}
        )
        enabled = wf.research.enabled
        return await self._go(
            run,
            S.RESEARCH if enabled else S.PLAN,
            TransitionContext(research_enabled=enabled, now=self.clock()),
        )

    async def _research(self, run: RunRecord, wf: WorkflowDefinition) -> RunRecord:
        import re

        placeholder = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
        ctx_vals: dict[str, Any] = {
            **(run.intent.entities if run.intent else {}),
            "category": run.intent.category if run.intent else "",
            **{k: v for k, v in run.input.items() if isinstance(v, str | int | float)},
        }
        m = await self._meter(run)
        ran: list[str] = []
        skipped: list[str] = []
        urls: list[str] = []
        for i, tmpl in enumerate(wf.research.queries, start=1):
            names = placeholder.findall(tmpl)
            if any(not ctx_vals.get(n) for n in names):
                skipped.append(tmpl)  # unresolved placeholder => skip rather than search garbage
                continue
            if m.research_queries >= self.limits.max_research_queries:
                raise LimitReached(f"research query cap {self.limits.max_research_queries} reached")
            m.research_queries += 1
            q = mask_pii(
                placeholder.sub(lambda mm: str(ctx_vals[mm.group(1)]), tmpl), include_contacts=True
            )
            r = await self._call_tool(
                run,
                wf,
                f"research-{i}",
                wf.research.tool,
                {
                    "query": q,
                    "max_results": min(wf.research.max_results_per_query, MAX_RESULTS_PER_BLOCK),
                    "allowed_domains": wf.research.allowed_domains,
                },
            )
            ran.append(q)
            res_urls = (
                [x.get("url", "") for x in r.output.get("results", [])] if r.status == "ok" else []
            )
            urls += res_urls
            await self._emit(
                run,
                S.RESEARCH,
                EventType.RESEARCH,
                {
                    "step_id": f"research-{i}",
                    "query": q,
                    "tool": wf.research.tool,
                    "status": r.status,
                    "result_count": len(res_urls),
                    "source_urls": res_urls,
                    "tool_call": True,
                    "untrusted": True,
                    "error": r.error,
                },
            )
            if r.status == "ok":
                await self._add_evidence(
                    run, f"research:{i}", "research", wf.research.tool, r.output
                )
        await self._emit(
            run,
            S.RESEARCH,
            EventType.RESEARCH,
            {"queries": ran, "skipped": skipped, "source_urls": urls},
        )
        return await self._go(run, S.PLAN)

    async def _plan(self, run: RunRecord, wf: WorkflowDefinition) -> RunRecord:
        evidence = await self.store.list_evidence(run.run_id)
        boundary = self._boundary(run)
        tool_lines = []
        for b in wf.tools:
            spec = self.tools.get_tool(b.tool)
            schema = json.dumps(spec.input_schema, separators=(",", ":")) if spec else "{}"
            tool_lines.append(f"- {b.tool} ({b.side_effect.value}) params schema: {schema}")
        system = (
            wf.planning.instructions
            + "\nAllowed action types: "
            + ", ".join(wf.planning.allowed_action_types)
            + f"\nAt most {wf.planning.max_steps} steps. Tools:\n"
            + "\n".join(tool_lines)
            + "\n\n"
            + UNTRUSTED_PREAMBLE
        )
        blocks = [
            wrap_untrusted(
                "intent_derived_from_user_input",
                _prompt_safe(run.intent.model_dump_json() if run.intent else "{}"),
                boundary,
            )
        ]
        research_n = 0
        for e in evidence:
            if e.kind == "research":
                research_n += 1
                if research_n > MAX_RESULTS_PER_BLOCK:
                    continue
            blocks.append(
                wrap_untrusted(
                    f"evidence:{e.key}",
                    _prompt_safe(json.dumps(e.content, ensure_ascii=False, default=str)),
                    boundary,
                )
            )
        res = await self._model(
            run,
            PlanProposal,
            [
                Message(role="system", content=system),
                Message(role="user", content="\n".join(blocks)),
            ],
            "plan",
            max_tokens=2048,
        )
        proposal: PlanProposal = res.output
        try:
            steps = self._validate_plan(wf, proposal)
        except SchemaViolation as exc:
            await self._emit(
                run,
                S.PLAN,
                EventType.POLICY,
                {
                    "outcome": "deny",
                    "rule_id": "plan-validation",
                    "code": "schema_violation",
                    "reason": str(exc),
                    "provider": self._provider_info(),
                    "no_retry": True,
                },
            )
            raise
        await self._emit(
            run,
            S.PLAN,
            EventType.PLAN,
            {
                "summary": proposal.summary,
                "steps": [s.model_dump() for s in steps],
                "provider": self._provider_info(),
                "tokens": res.usage.input_tokens + res.usage.output_tokens,
                "latency_ms": res.usage.latency_ms,
            },
        )
        return await self._go(run, S.POLICY, plan=steps)

    def _validate_plan(self, wf: WorkflowDefinition, proposal: PlanProposal) -> list[PlanStep]:
        """Deterministic plan validation (U2b/c). No retry with looser rules: raise."""
        if not 1 <= len(proposal.steps) <= wf.planning.max_steps:
            raise SchemaViolation(
                f"plan has {len(proposal.steps)} steps; allowed 1..{wf.planning.max_steps}"
            )
        steps: list[PlanStep] = []
        for n, p in enumerate(proposal.steps, start=1):
            if wf.tool_side_effect(p.tool_name) is None:
                raise SchemaViolation(
                    f"plan uses tool {p.tool_name!r} that the workflow does not list"
                )
            if p.action_type not in wf.planning.allowed_action_types:
                raise SchemaViolation(
                    f"plan uses action_type {p.action_type!r} the workflow does not allow"
                )
            spec = self.tools.get_tool(p.tool_name)
            if spec is None:
                raise SchemaViolation(f"plan uses unregistered tool {p.tool_name!r}")
            validate_params(spec.input_schema, p.params)
            steps.append(
                PlanStep(
                    step_id=f"step-{n}",
                    action_type=p.action_type,
                    tool_name=p.tool_name,
                    params=p.params,
                    rationale=p.rationale,
                )
            )
        return steps

    async def _policy(self, run: RunRecord, wf: WorkflowDefinition) -> RunRecord:
        decisions = []
        for step in run.plan:
            req = action_for_step(run.run_id, wf, step, run.owner)
            d = self.policy.evaluate(req, wf.policy, self.tools.get_tool(step.tool_name))
            decisions.append(d)
            await self._emit(
                run,
                S.POLICY,
                EventType.POLICY,
                {
                    "step_id": step.step_id,
                    "tool": step.tool_name,
                    "outcome": d.outcome.value,
                    "risk": d.risk.value,
                    "rule_id": d.rule_id,
                    "reason": d.reason,
                    "policy_version": d.policy_version,
                    "action_digest": d.action_digest,
                },
            )
        outcomes = {d.outcome for d in decisions}
        if PolicyOutcome.DENY in outcomes:
            denied = next(d for d in decisions if d.outcome == PolicyOutcome.DENY)
            return await self._go(
                run,
                S.DENIED,
                TransitionContext(
                    reason=f"policy denied {denied.step_id}: {denied.reason}", now=self.clock()
                ),
                decisions=decisions,
            )
        if PolicyOutcome.NEEDS_APPROVAL in outcomes:
            new = await self._go(run, S.APPROVAL, decisions=decisions)
            for step, d in zip(new.plan, new.decisions, strict=True):
                if d.outcome == PolicyOutcome.NEEDS_APPROVAL:
                    req = action_for_step(run.run_id, wf, step, run.owner)
                    summary = (
                        f"{step.action_type}: {step.tool_name} "
                        + json.dumps(step.params, ensure_ascii=False)[:300]
                    )
                    ap = await self.approvals.create(req, d, summary, wf.approvals.ttl_seconds)
                    await self._emit(
                        new,
                        S.APPROVAL,
                        EventType.APPROVAL,
                        {
                            "approval_id": ap.approval_id,
                            "step_id": step.step_id,
                            "status": "pending",
                            "tool": step.tool_name,
                            "params": step.params,
                            "summary": ap.summary,
                            "risk": ap.risk.value,
                            "action_digest": ap.bound_digest,
                            "simulated": wf.tool_side_effect(step.tool_name)
                            == SideEffect.MOCK_WRITE,
                            "expires_at": ap.expires_at.isoformat(),
                        },
                    )
                    await self._audit(
                        new,
                        "system",
                        "approval_requested",
                        {"approval_id": ap.approval_id, "digest": ap.bound_digest},
                    )
            return new
        return await self._go(run, S.ACTION, decisions=decisions)

    async def _approval(self, run: RunRecord, wf: WorkflowDefinition) -> RunRecord | None:
        aps = await self.approvals.list_for_run(run.run_id)
        bad = next(
            (
                a
                for a in aps
                if a.status
                in (ApprovalStatus.DENIED, ApprovalStatus.EXPIRED, ApprovalStatus.REVOKED)
            ),
            None,
        )
        if bad is not None:
            return await self._go(
                run,
                S.DENIED,
                TransitionContext(
                    reason=f"approval for {bad.step_id} was {bad.status.value}", now=self.clock()
                ),
            )
        if any(a.status == ApprovalStatus.PENDING for a in aps):
            if run.state == S.APPROVAL:
                await self._emit(
                    run,
                    S.APPROVAL,
                    EventType.APPROVAL,
                    {
                        "status": "awaiting_human_decision",
                        "pending": [
                            a.approval_id for a in aps if a.status == ApprovalStatus.PENDING
                        ],
                    },
                )
            return None
        gated = [
            action_for_step(run.run_id, wf, s, run.owner)
            for s, d in zip(run.plan, run.decisions, strict=True)
            if d.outcome == PolicyOutcome.NEEDS_APPROVAL
        ]
        return await self._go(
            run, S.ACTION, TransitionContext(gated_actions=gated, approvals=aps, now=self.clock())
        )

    async def _action(self, run: RunRecord, wf: WorkflowDefinition) -> RunRecord:
        aps = {a.step_id: a for a in await self.approvals.list_for_run(run.run_id)}
        results = list(run.results)
        failed_already = any(r.status != "ok" for r in results)
        for idx in range(len(results), len(run.plan)):
            if failed_already:
                break
            step = run.plan[idx]
            ap = aps.get(step.step_id)
            if ap is not None and ap.status == ApprovalStatus.CONSUMED:
                raise ce.ApprovalError(
                    f"approval for {step.step_id} was consumed but no result is recorded; "
                    "outcome unknown, refusing to re-execute (needs human review)"
                )
            r = await self._call_tool(
                run,
                wf,
                step.step_id,
                step.tool_name,
                step.params,
                approval_id=ap.approval_id if ap else None,
            )
            results.append(r)
            await self._emit(
                run,
                S.ACTION,
                EventType.ACTION,
                {
                    "step_id": step.step_id,
                    "tool": step.tool_name,
                    "status": r.status,
                    "mocked": r.mocked,
                    "label": "SIMULATED" if r.mocked else "",
                    "output": r.output,
                    "error": r.error,
                    "tool_call": True,
                },
            )
            run = await self._save_progress(run, results=results)
            if r.status != "ok":
                failed_already = True
        if failed_already and len(results) < len(run.plan):
            await self._emit(
                run,
                S.ACTION,
                EventType.ACTION,
                {
                    "skipped_steps": [s.step_id for s in run.plan[len(results) :]],
                    "reason": "an earlier action failed",
                },
            )
        return await self._go(run, S.VERIFICATION)

    async def _verification(self, run: RunRecord, wf: WorkflowDefinition) -> RunRecord:
        vr = await self.verifier.verify(
            run, wf.verification, await self.store.list_evidence(run.run_id), run.results
        )
        action_failed = any(r.status != "ok" for r in run.results)
        await self._emit(
            run,
            S.VERIFICATION,
            EventType.VERIFICATION,
            {**vr.model_dump(mode="json"), "action_failed": action_failed},
        )
        if not vr.passed or action_failed:
            failing = [c.check_id for c in vr.checks if not c.passed]
            base = run.model_copy(update={"verification": vr})
            reason = "verification failed: " + (", ".join(failing) or "an action failed")
            await self._emit(
                base,
                S.VERIFICATION,
                EventType.ERROR,
                {"reason": reason, "code": "verification_failed"},
            )
            saved = await self._save_progress(run, verification=vr)
            return await self._go(
                saved, S.FAILED, TransitionContext(reason=reason, now=self.clock())
            )
        return await self._go(run, S.AUDIT, verification=vr)

    async def _audit_stage(self, run: RunRecord, wf: WorkflowDefinition) -> RunRecord:
        recs = await self.audit.list_for_run(run.run_id)
        head = recs[-1].hash if recs else ""
        await self._audit(
            run,
            "system",
            "run_summary",
            {
                "steps": len(run.plan),
                "verification_passed": bool(run.verification and run.verification.passed),
                "provider": self._provider_info(),
            },
        )
        await self._emit(
            run,
            S.AUDIT,
            EventType.AUDIT,
            {
                "audit_records": len(recs) + 1,
                "chain_head_before_summary": head,
                "provider": self._provider_info(),
            },
        )
        done = await self._go(run, S.COMPLETED)
        await self._write_memory(done, outcome="completed")
        return done

    async def _write_memory(self, run: RunRecord, outcome: str) -> None:
        """Per-run and per-user memory (values are redacted by the Memory implementation)."""
        if self.memory is None:
            return
        try:
            await self.memory.put(MemoryScope.RUN, run.run_id, "outcome", outcome)
            if run.intent:
                await self.memory.put(
                    MemoryScope.RUN, run.run_id, "intent", run.intent.model_dump()
                )
            await self.memory.put(
                MemoryScope.USER,
                run.owner,
                "last_run",
                {
                    "run_id": run.run_id,
                    "workflow_id": run.workflow_id,
                    "outcome": outcome,
                    "summary": run.intent.summary if run.intent else "",
                },
            )
        except Exception as exc:
            log.warning("memory write failed: %s", type(exc).__name__)
