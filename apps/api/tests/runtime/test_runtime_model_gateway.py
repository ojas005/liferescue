"""Model gateway: structured outputs, repair/fail-closed, Mock + Nebius providers (fake HTTP only)."""

from __future__ import annotations

import json

import httpx
import pytest
from contract import errors as ce
from contract.models import IntentResult, Message
from demo_support import run_async
from pydantic import BaseModel, ConfigDict, Field

from app.runtime.errors import LimitReached, NotConfigured
from app.runtime.model_gateway import (
    MOCK_LABEL,
    AIProvider,
    MockAIProvider,
    ModelBudget,
    ModelGateway,
    NebiusProvider,
    default_instance,
    extract_json,
    provider_from_env,
)

# Fake key assembled at runtime so no key-shaped literal lives in the repo.
FAKE_KEY = "fake" + "-key-" + "A1b2C3d4E5f6"


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(max_length=20)
    score: int = Field(ge=0, le=10)


MSGS = [Message(role="user", content="classify")]


def call(p, schema=Verdict):
    return run_async(p.complete_structured(schema, MSGS, purpose="t", run_id="r1"))


# ----------------------------------------------------------------------------- mock + loop
def test_mock_is_schema_valid_by_default_and_labelled():
    p = MockAIProvider()
    res = call(p, Verdict)
    assert isinstance(res.output, Verdict) and res.adapter == "mock" and res.model == "mock-model"
    assert p.label == MOCK_LABEL and "MOCK" in p.label
    assert isinstance(p, AIProvider) and isinstance(p, ModelGateway)
    assert run_async(p.health_check()).ok


def test_default_instance_handles_nested_optional_enum():
    from enum import Enum

    class Color(str, Enum):
        RED = "red"

    class Inner(BaseModel):
        n: int = Field(ge=3)

    class Outer(BaseModel):
        c: Color
        inner: Inner
        tags: list[str]
        maybe: str | None
        flag: bool

    out = default_instance(Outer)
    assert out.c == Color.RED and out.inner.n == 3 and out.tags == []


def test_repair_retry_succeeds_and_prompt_contains_error_but_not_input_values():
    p = MockAIProvider(['{"label": "ok", "score": 99}', '```json\n{"label":"ok","score":7}\n```'])
    res = call(p)
    assert res.output.score == 7 and len(p.calls) == 2 and p.stats.repairs == 1
    repair_msgs = p.calls[1]["messages"]
    assert repair_msgs[-1].role == "user" and "score" in repair_msgs[-1].content
    assert repair_msgs[-2].role == "assistant"
    assert "99" not in repair_msgs[-1].content  # error text never echoes submitted values


def test_fail_closed_after_max_repairs_with_typed_error():
    p = MockAIProvider(
        ["nope", '{"label": 1}', '{"label":"x","score":-1}', '{"label":"x","score":1}']
    )
    with pytest.raises(ce.ModelSchemaError):
        call(p)
    assert len(p.calls) == 3  # 1 try + 2 repairs; the 4th scripted (valid) reply is never used


def test_extra_fields_are_rejected_not_ignored():
    p = MockAIProvider(['{"label":"a","score":1,"is_admin":true}'] * 3)
    with pytest.raises(ce.ModelSchemaError):
        call(p)


def test_max_repairs_cannot_exceed_two():
    with pytest.raises(ValueError):
        MockAIProvider(max_repairs=3)


def test_extract_json_variants():
    assert extract_json('<think>hmm {"a":0}</think>{"a":1}') == {"a": 1}
    assert extract_json('Sure! Here: {"a": {"b": 2}} done') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_budget_caps_calls_and_tokens():
    p = MockAIProvider(budget=ModelBudget(max_calls=1))
    call(p)
    with pytest.raises(LimitReached):
        call(p)
    q = MockAIProvider(budget=ModelBudget(max_total_tokens=5))
    call(q)
    with pytest.raises(LimitReached):
        call(q)


def test_provider_selection_and_mock_production_guard():
    p = provider_from_env({"AI_PROVIDER": "mock", "LIFERESCUE_ENV": "development"})
    assert p.adapter_kind == "mock"
    with pytest.raises(ce.ConfigError):  # contract default env is production
        provider_from_env({"AI_PROVIDER": "mock"})
    with pytest.raises(ce.ConfigError):
        provider_from_env({"AI_PROVIDER": "mock", "LIFERESCUE_ENV": "staging"})
    with pytest.raises(ce.ConfigError):
        provider_from_env({"AI_PROVIDER": "openai", "LIFERESCUE_ENV": "development"})
    n = provider_from_env({"LIFERESCUE_ENV": "production"})
    assert n.adapter_kind == "nebius"


# ----------------------------------------------------------------------------- nebius (fake HTTP)
def completion(content, usage=(11, 5), model="nvidia/test-model"):
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
        "model": model,
    }


def nebius(handler, **kw):
    kw.setdefault("sleep", _nosleep)
    return NebiusProvider(
        api_key=kw.pop("api_key", FAKE_KEY),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        **kw,
    )


async def _nosleep(_s):
    return None


def test_nebius_request_shape_and_usage_metadata():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=completion('{"label":"fine","score":3}'))

    p = nebius(handler, model="nvidia/test-model", base_url="https://example-nebius.test/v1/")
    res = call(p)
    assert res.output == Verdict(label="fine", score=3)
    assert seen["url"] == "https://example-nebius.test/v1/chat/completions"
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    b = seen["body"]
    assert b["model"] == "nvidia/test-model" and b["temperature"] == 0
    assert b["response_format"]["type"] == "json_schema"
    assert b["response_format"]["json_schema"]["schema"]["title"] == "Verdict"
    assert b["messages"][0]["role"] == "system" and "JSON Schema" in b["messages"][0]["content"]
    assert (res.usage.input_tokens, res.usage.output_tokens) == (11, 5)
    assert res.adapter == "nebius" and res.model == "nvidia/test-model"
    assert p.model_id == "nvidia/test-model" and p.stats.last_attempts == 1


def test_nebius_defaults_documented_endpoint_and_model(monkeypatch):
    p = NebiusProvider(api_key=FAKE_KEY)
    assert p.base_url == "https://api.tokenfactory.us-central1.nebius.com/v1"
    assert p.model_id == "nvidia/nemotron-3-super-120b-a12b"
    monkeypatch.setenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
    monkeypatch.setenv("NEBIUS_MODEL", "nvidia/other")
    q = NebiusProvider(api_key=FAKE_KEY)
    assert q.base_url == "https://api.tokenfactory.nebius.com/v1" and q.model_id == "nvidia/other"
    with pytest.raises(ce.ConfigError):
        NebiusProvider(api_key=FAKE_KEY, base_url="http://insecure.test/v1")


def test_nebius_repairs_malformed_json_then_succeeds():
    replies = iter(['{"label": "x"}', '{"label":"x","score":2}'])

    def handler(req):
        return httpx.Response(200, json=completion(next(replies)))

    res = call(nebius(handler))
    assert res.output.score == 2 and res.usage.input_tokens == 22  # usage summed across attempts


def test_nebius_degrades_response_format_on_400():
    modes = []

    def handler(req):
        body = json.loads(req.content)
        modes.append((body.get("response_format") or {}).get("type"))
        if len(modes) < 3:
            return httpx.Response(400, json={"error": "response_format unsupported"})
        return httpx.Response(200, json=completion('{"label":"a","score":1}'))

    p = nebius(handler)
    assert call(p).output.label == "a"
    assert modes == ["json_schema", "json_object", None]
    assert p.response_mode == "prompt"


def test_nebius_retries_transient_then_gives_up_typed():
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        return httpx.Response(503, text="busy")

    with pytest.raises(ce.ModelUnavailable):
        call(nebius(handler, http_retries=2))
    assert n["c"] == 3

    n["c"] = 0

    def flaky(req):
        n["c"] += 1
        if n["c"] == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json=completion('{"label":"a","score":1}'))

    assert call(nebius(flaky)).output.label == "a"


def test_nebius_timeout_and_malformed_and_refusal_map_to_model_unavailable():
    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(ce.ModelUnavailable):
        call(nebius(timeout, http_retries=0))
    for payload in ({"nonsense": 1}, completion(""), {"choices": [{"message": {"refusal": "no"}}]}):
        with pytest.raises(ce.ModelUnavailable):
            call(nebius(lambda req, p=payload: httpx.Response(200, json=p)))


def test_nebius_missing_key_raises_not_configured_without_network():
    def handler(req):
        raise AssertionError("network must not be touched")

    p = NebiusProvider(env={}, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(NotConfigured) as ei:
        call(p)
    assert "NEBIUS_API_KEY" in str(ei.value) and "key not provided" in str(ei.value)
    h = run_async(p.health_check())
    assert h.ok is False and h.detail == "key not provided"


def test_nebius_key_from_env_only_and_never_in_repr_errors_or_logs(monkeypatch, caplog):
    monkeypatch.setenv("NEBIUS_API_KEY", FAKE_KEY)

    def handler(req):  # hostile server echoes the credential back in an error body
        return httpx.Response(401, text=f"bad credential {FAKE_KEY} / Bearer {FAKE_KEY}")

    p = NebiusProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert p.is_configured() and FAKE_KEY not in repr(p)
    with caplog.at_level("DEBUG"), pytest.raises(ce.ModelUnavailable) as ei:
        call(p)
    assert FAKE_KEY not in str(ei.value) and "401" in str(ei.value)
    assert FAKE_KEY not in caplog.text


def test_nebius_health_check_ok_and_failure():
    ok = nebius(lambda req: httpx.Response(200, json={"data": []}))
    assert run_async(ok.health_check()).ok
    bad = nebius(lambda req: httpx.Response(403, text="no"))
    h = run_async(bad.health_check())
    assert h.ok is False and "403" in h.detail


def test_intent_result_round_trip_through_real_provider_path():
    payload = IntentResult(summary="s", category="c").model_dump_json()
    res = run_async(
        nebius(lambda req: httpx.Response(200, json=completion(payload))).complete_structured(
            IntentResult, MSGS, purpose="intent"
        )
    )
    assert isinstance(res.output, IntentResult)
