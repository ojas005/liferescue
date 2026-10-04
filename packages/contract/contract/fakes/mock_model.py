"""MockModel: deterministic ModelGateway for dev/tests. NEVER allowed in production config (see assert_model_adapter_allowed)."""
from __future__ import annotations

from typing import Any, Callable, Literal, Sequence, TypeVar

from pydantic import BaseModel

from ..errors import ModelSchemaError
from ..interfaces import StructuredResult
from ..models import AssessmentResult, IntentResult, Message, PlanProposal, PlanStepProposal, RiskLevel, Usage

T = TypeVar("T", bound=BaseModel)
Responder = Callable[[Sequence[Message]], BaseModel]


class MockModel:
    adapter_kind: Literal["nebius", "mock"] = "mock"

    def __init__(self, responders: dict[type, Responder | BaseModel] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._r: dict[type, Responder | BaseModel] = {
            IntentResult: IntentResult(summary="Car will not start on a highway shoulder", category="breakdown",
                                       urgency=RiskLevel.MEDIUM, entities={"location": "Pune", "vehicle": "Hyundai i20"}),
            PlanProposal: PlanProposal(steps=[
                PlanStepProposal(action_type="request_tow", tool_name="dispatch_tow", params={"location": "Pune"}, rationale="Vehicle cannot be driven."),
                PlanStepProposal(action_type="notify_contact", tool_name="send_message", params={"to": "emergency-contact", "text": "Tow requested."}, rationale="Let a contact know."),
            ]),
            AssessmentResult: AssessmentResult(satisfied=True, explanation="mock assessment"),
        }
        if responders:
            self._r.update(responders)

    async def complete_structured(self, schema: type[T], messages: Sequence[Message], *, purpose: str, run_id: str | None = None,
                                  max_tokens: int = 1024, timeout_s: float = 30.0) -> StructuredResult:
        self.calls.append({"schema": schema.__name__, "purpose": purpose, "run_id": run_id, "n_messages": len(messages)})
        r = self._r.get(schema)
        if r is None:
            raise ModelSchemaError(f"MockModel has no responder for {schema.__name__}")
        out = r(messages) if callable(r) else r
        validated = schema.model_validate(out.model_dump())  # same validation a real gateway applies
        return StructuredResult(output=validated, model="mock-model", adapter="mock", usage=Usage(input_tokens=1, output_tokens=1, latency_ms=1))
