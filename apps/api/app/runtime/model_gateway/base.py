"""AI provider abstraction: AIProvider (superset of the contract's ModelGateway), MockAIProvider,
config-driven selection, and the shared validate -> repair -> fail-closed loop.

* `AIProvider` = contract `ModelGateway` + `health_check` + `model_id` + metadata. `ModelGateway`
  is re-exported as an alias: any AIProvider satisfies the contract Protocol.
* Mock output is NEVER presentable as real AI: `adapter_kind == "mock"`, `label` is
  "MOCK (scripted, not real AI)", and the engine stamps `provider`/`label`/`mock: true` on every
  timeline event that carries model output.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable

from contract import errors as ce
from contract.interfaces import ModelGateway, StructuredResult
from contract.models import (
    Message,
    StrictModel,
    Usage,
)
from pydantic import BaseModel, ValidationError

from ..errors import LimitReached
from ..redaction import redact_text

T = TypeVar("T", bound=BaseModel)

ScriptItem = str | Mapping[str, Any] | BaseModel | Exception
Responder = Callable[[Sequence[Message]], BaseModel]

MOCK_LABEL = "MOCK (scripted, not real AI)"

__all__ = [
    "MOCK_LABEL",
    "AIProvider",
    "ModelBudget",
    "ModelGateway",
    "ProviderBase",
    "ProviderHealth",
    "ProviderStats",
    "RawCompletion",
    "extract_json",
]


class ProviderHealth(StrictModel):
    ok: bool
    provider: str
    model: str
    latency_ms: int = 0
    detail: str = ""


@runtime_checkable
class AIProvider(Protocol):
    """What the engine needs. Satisfies the contract's ModelGateway Protocol (alias below)."""

    adapter_kind: Literal["nebius", "mock"]
    model_id: str
    label: str

    async def complete_structured(
        self,
        schema: type[T],
        messages: Sequence[Message],
        *,
        purpose: str,
        run_id: str | None = None,
        max_tokens: int = 1024,
        timeout_s: float = 30.0,
    ) -> StructuredResult: ...

    async def health_check(self) -> ProviderHealth: ...


@dataclass
class RawCompletion:
    text: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""


@dataclass
class ProviderStats:
    calls: int = 0  # structured calls
    raw_calls: int = 0  # raw model round trips (>= calls when repairs happen)
    repairs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    last_latency_ms: int = 0
    last_attempts: int = 0


class ModelBudget:
    """Process-wide call/token cap for one provider instance (thread-safe). Per-run caps (U5) are
    enforced by the engine; this is the global cost backstop."""

    def __init__(self, max_calls: int | None = None, max_total_tokens: int | None = None) -> None:
        self.max_calls, self.max_total_tokens = max_calls, max_total_tokens
        self.calls = 0
        self.tokens = 0
        self._lock = threading.Lock()

    def before_call(self) -> None:
        with self._lock:
            if self.max_calls is not None and self.calls >= self.max_calls:
                raise LimitReached(f"model call budget exhausted ({self.max_calls})")
            if self.max_total_tokens is not None and self.tokens >= self.max_total_tokens:
                raise LimitReached(f"model token budget exhausted ({self.max_total_tokens})")
            self.calls += 1

    def record(self, usage: Usage) -> None:
        with self._lock:
            self.tokens += usage.input_tokens + usage.output_tokens


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```\s*$", re.S)


def extract_json(text: str) -> Any:
    """Parse a JSON object from model text (handles fences, <think> blocks, surrounding prose)."""
    cleaned = _THINK.sub("", text or "").strip()
    fence = _FENCE.match(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", cleaned):
        try:
            obj, _ = decoder.raw_decode(cleaned[m.start() :])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("no JSON object found in model output")


def _describe_error(exc: Exception, limit: int = 1200) -> str:
    """Compact validation feedback for the repair prompt. Never echoes input values."""
    if isinstance(exc, ValidationError):
        lines = []
        for err in exc.errors(include_url=False, include_input=False, include_context=False)[:12]:
            loc = ".".join(str(p) for p in err["loc"]) or "(root)"
            lines.append(f"- {loc}: {err['msg']}")
        text = "Schema validation failed:\n" + "\n".join(lines)
    else:
        text = f"Output was not valid JSON: {exc}"
    return redact_text(text, max_len=limit)


def schema_instructions(schema: type[BaseModel]) -> str:
    return (
        "Respond with ONE JSON object and nothing else (no markdown, no commentary). It must "
        "validate against this JSON Schema (unknown fields are rejected):\n"
        + json.dumps(schema.model_json_schema(), separators=(",", ":"))
    )


class ProviderBase:
    """Validate -> repair (<= max_repairs, default 2 per U2) -> fail closed. Subclasses implement
    `_complete_raw` and `health_check`."""

    adapter_kind: Literal["nebius", "mock"] = "mock"
    model_id: str = "unknown"
    label: str = "unknown"

    def __init__(self, *, max_repairs: int = 2, budget: ModelBudget | None = None) -> None:
        if not 0 <= max_repairs <= 2:
            raise ValueError("max_repairs must be 0..2 (security requirement U2)")
        self.max_repairs = max_repairs
        self.budget = budget or ModelBudget()
        self.stats = ProviderStats()

    async def _complete_raw(
        self, messages: list[Message], schema: type[BaseModel], *, max_tokens: int, timeout_s: float
    ) -> RawCompletion:
        raise NotImplementedError

    async def health_check(self) -> ProviderHealth:  # pragma: no cover - overridden
        raise NotImplementedError

    async def complete_structured(
        self,
        schema: type[T],
        messages: Sequence[Message],
        *,
        purpose: str,
        run_id: str | None = None,
        max_tokens: int = 1024,
        timeout_s: float = 30.0,
    ) -> StructuredResult:
        msgs: list[Message] = [Message(role="system", content=schema_instructions(schema))]
        msgs += [m if isinstance(m, Message) else Message.model_validate(m) for m in messages]
        started = time.perf_counter()
        in_tok = out_tok = 0
        last_problem = "no attempt made"
        self.stats.calls += 1
        for attempt in range(self.max_repairs + 1):
            self.budget.before_call()
            self.stats.raw_calls += 1
            raw = await self._complete_raw(msgs, schema, max_tokens=max_tokens, timeout_s=timeout_s)
            self.budget.record(raw.usage)
            in_tok += raw.usage.input_tokens
            out_tok += raw.usage.output_tokens
            try:
                value = schema.model_validate(extract_json(raw.text))
            except ValueError as exc:  # JSON errors and pydantic ValidationError
                last_problem = _describe_error(exc)
                self.stats.repairs += 1
                msgs = msgs + [
                    Message(role="assistant", content=redact_text(raw.text, max_len=2000)),
                    Message(
                        role="user",
                        content=(
                            f"Your previous reply was rejected. {last_problem}\n"
                            "Reply again with ONE corrected JSON object only."
                        ),
                    ),
                ]
                continue
            latency = int((time.perf_counter() - started) * 1000)
            self.stats.input_tokens += in_tok
            self.stats.output_tokens += out_tok
            self.stats.last_latency_ms, self.stats.last_attempts = latency, attempt + 1
            return StructuredResult(
                output=value,
                model=raw.model or self.model_id,
                adapter=self.adapter_kind,
                usage=Usage(input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency),
            )
        self.stats.last_attempts = self.max_repairs + 1
        raise ce.ModelSchemaError(
            redact_text(
                f"{purpose}: model output did not match {schema.__name__} after "
                f"{self.max_repairs + 1} attempts; last problem: {last_problem}"
            )
        )
