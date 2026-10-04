"""Verification engine: contract `Verifier` + pluggable per-workflow hooks.

Built-in checks follow the WorkflowDefinition's VerificationStrategy (tool_result_status,
evidence_present, model_assessment). Workflow-specific verifiers register as hooks; a hook that
raises counts as a FAILED check (fail closed). A failed verification fails the run (contract:
VERIFICATION -> FAILED) and the result is recorded as a `verification` timeline event by the engine.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence

from contract.models import (
    AssessmentResult,
    CheckResult,
    Evidence,
    Message,
    RunRecord,
    ToolResult,
    VerificationResult,
)
from contract.workflow_definition import VerificationStrategy

from app.runtime.model_gateway import AIProvider
from app.runtime.redaction import redact_text
from app.runtime.untrusted import UNTRUSTED_PREAMBLE, new_boundary, wrap_untrusted

Hook = Callable[
    [RunRecord, Sequence[Evidence], Sequence[ToolResult]], CheckResult | Awaitable[CheckResult]
]


class RuntimeVerifier:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self._provider = provider
        self._hooks: dict[str, list[Hook]] = {}

    def register_hook(self, workflow_id: str, hook: Hook) -> None:
        self._hooks.setdefault(workflow_id, []).append(hook)

    async def verify(
        self,
        run: RunRecord,
        strategy: VerificationStrategy,
        evidence: Sequence[Evidence],
        results: Sequence[ToolResult],
    ) -> VerificationResult:
        checks: list[CheckResult] = []
        for c in strategy.checks:
            try:
                checks.append(await self._builtin(run, c, evidence, results))
            except Exception as exc:
                checks.append(
                    CheckResult(
                        check_id=c.check_id,
                        passed=False,
                        detail=f"check error: {type(exc).__name__}",
                    )
                )
        hook_checks: list[CheckResult] = []
        for i, hook in enumerate(self._hooks.get(run.workflow_id, [])):
            try:
                r = hook(run, evidence, results)
                hook_checks.append(await r if inspect.isawaitable(r) else r)
            except Exception as exc:
                hook_checks.append(
                    CheckResult(
                        check_id=f"hook-{i}",
                        passed=False,
                        detail=f"verifier error: {type(exc).__name__}",
                    )
                )
        passed = (
            all(c.passed for c in checks) if strategy.require_all else any(c.passed for c in checks)
        )
        passed = passed and all(c.passed for c in hook_checks)  # hooks are always mandatory
        return VerificationResult(passed=passed, checks=checks + hook_checks)

    async def _builtin(
        self,
        run: RunRecord,
        c: object,
        evidence: Sequence[Evidence],
        results: Sequence[ToolResult],
    ) -> CheckResult:
        kind = c.kind  # type: ignore[attr-defined]
        cid = c.check_id  # type: ignore[attr-defined]
        if kind == "tool_result_status":
            rs = [r for r in results if r.tool_name == c.tool]  # type: ignore[attr-defined]
            ok = all(r.status == "ok" for r in rs)
            return CheckResult(
                check_id=cid,
                passed=ok,
                detail=f"{len(rs)} call(s), {'all ok' if ok else 'some failed'}",
            )
        if kind == "evidence_present":
            ok = any(e.key == c.evidence_key for e in evidence)  # type: ignore[attr-defined]
            return CheckResult(check_id=cid, passed=ok, detail="present" if ok else "missing")
        if self._provider is None:
            return CheckResult(
                check_id=cid, passed=False, detail="no model available for assessment"
            )
        boundary = new_boundary()
        res = await self._provider.complete_structured(
            AssessmentResult,
            [
                Message(
                    role="system",
                    content="Answer the question about the run outcome. " + UNTRUSTED_PREAMBLE,
                ),
                Message(
                    role="user",
                    content=f"Question: {c.question}\n"  # type: ignore[attr-defined]
                    + wrap_untrusted(
                        "tool_results",
                        str([r.model_dump(mode="json") for r in results]),
                        boundary,
                    ),
                ),
            ],
            purpose="verification",
            run_id=run.run_id,
        )
        out: AssessmentResult = res.output
        return CheckResult(
            check_id=cid, passed=out.satisfied, detail=redact_text(out.explanation, max_len=300)
        )
