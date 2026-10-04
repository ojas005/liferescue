"""MockAIProvider: deterministic dev/test model. Blocked in production/staging by the contract guard
(`assert_model_adapter_allowed`). Output is visibly labelled mock everywhere it is shown."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypeVar

from contract.models import (
    AssessmentResult,
    IntentResult,
    Message,
    PlanProposal,
    PlanStepProposal,
    RiskLevel,
    SideEffect,
    Usage,
)
from contract.workflow_definition import WorkflowDefinition
from pydantic import BaseModel

from .base import (
    MOCK_LABEL,
    ModelBudget,
    ProviderBase,
    ProviderHealth,
    RawCompletion,
    Responder,
    ScriptItem,
)

T = TypeVar("T", bound=BaseModel)


def default_instance(schema: type[T]) -> T:
    """Minimal schema-valid instance of any pydantic model (deterministic)."""

    def build(node: dict[str, Any], defs: dict[str, Any]) -> Any:
        if "$ref" in node:
            return build(defs[node["$ref"].split("/")[-1]], defs)
        if "default" in node:
            return node["default"]
        if "enum" in node:
            return node["enum"][0]
        if "const" in node:
            return node["const"]
        for key in ("anyOf", "oneOf"):
            if key in node:
                options = [o for o in node[key] if o.get("type") != "null"]
                return build(options[0], defs) if options else None
        t = node.get("type")
        if t == "object" or "properties" in node:
            required = set(node.get("required", []))
            return {
                k: build(v, defs) for k, v in node.get("properties", {}).items() if k in required
            }
        if t == "array":
            n = node.get("minItems", 0)
            return [build(node.get("items", {}), defs) for _ in range(n)]
        if t == "string":
            return "mock" * max(1, (node.get("minLength", 0) + 3) // 4)
        if t == "integer":
            return int(node.get("minimum", 0))
        if t == "number":
            return float(node.get("minimum", 0))
        if t == "boolean":
            return False
        return None

    js = schema.model_json_schema()
    return schema.model_validate(build(js, js.get("$defs", {})))


class MockAIProvider(ProviderBase):
    """Deterministic provider for dev/tests. Output is schema-valid by default.

    Resolution per raw call: `script` item (consumed in order) > `responders[schema]` > built-in
    default for IntentResult / PlanProposal / AssessmentResult > schema-valid minimal instance.
    Script items may be raw JSON text, dict, pydantic model, or an Exception (raised) so tests can
    inject adversarial or malformed replies; malformed replies go through the SAME repair/fail-
    closed loop as the real provider.
    """

    adapter_kind: Literal["nebius", "mock"] = "mock"
    label = MOCK_LABEL

    def __init__(
        self,
        script: Sequence[ScriptItem] | None = None,
        *,
        responders: Mapping[type, Responder | BaseModel] | None = None,
        workflow: WorkflowDefinition | None = None,
        max_repairs: int = 2,
        budget: ModelBudget | None = None,
    ) -> None:
        super().__init__(max_repairs=max_repairs, budget=budget)
        self.model_id = "mock-model"
        self._script: list[ScriptItem] = list(script or [])
        self._responders: dict[type, Responder | BaseModel] = {
            IntentResult: IntentResult(
                summary="Mock: car will not start on a highway shoulder",
                category="breakdown",
                urgency=RiskLevel.MEDIUM,
                entities={"location": "Pune", "vehicle": "Hyundai i20"},
            ),
            PlanProposal: self._default_plan(workflow),
            AssessmentResult: AssessmentResult(satisfied=True, explanation="mock assessment"),
        }
        self._responders.update(responders or {})
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _default_plan(workflow: WorkflowDefinition | None) -> PlanProposal:
        if workflow is None:
            return PlanProposal(
                steps=[
                    PlanStepProposal(
                        action_type="request_tow",
                        tool_name="dispatch_tow",
                        params={"location": "Pune"},
                        rationale="Vehicle cannot be driven.",
                    ),
                    PlanStepProposal(
                        action_type="notify_contact",
                        tool_name="send_message",
                        params={"to": "emergency-contact", "text": "Tow requested."},
                        rationale="Let a contact know.",
                    ),
                ],
                summary="mock plan",
            )
        actions = workflow.planning.allowed_action_types
        steps = [
            PlanStepProposal(
                action_type=actions[min(i, len(actions) - 1)],
                tool_name=b.tool,
                params={},
                rationale="mock rationale",
            )
            for i, b in enumerate(
                b for b in workflow.tools if b.side_effect == SideEffect.MOCK_WRITE
            )
        ]
        return PlanProposal(steps=steps[: workflow.planning.max_steps] or [], summary="mock plan")

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(ok=True, provider="mock", model=self.model_id, detail=MOCK_LABEL)

    async def _complete_raw(
        self, messages: list[Message], schema: type[BaseModel], *, max_tokens: int, timeout_s: float
    ) -> RawCompletion:
        self.calls.append(
            {"schema": schema.__name__, "messages": [m.model_copy() for m in messages]}
        )
        item: ScriptItem
        if self._script:
            item = self._script.pop(0)
        elif schema in self._responders:
            r = self._responders[schema]
            item = r(messages) if callable(r) else r
        else:
            item = default_instance(schema)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, BaseModel):
            text = item.model_dump_json()
        elif isinstance(item, str):
            text = item
        else:
            text = json.dumps(dict(item))
        n = max(1, len(text) // 4)
        return RawCompletion(
            text=text,
            usage=Usage(input_tokens=10, output_tokens=n, latency_ms=1),
            model=self.model_id,
        )
