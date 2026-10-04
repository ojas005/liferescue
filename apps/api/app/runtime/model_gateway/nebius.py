"""NebiusProvider: OpenAI-compatible chat completions for NVIDIA Nemotron on Nebius Token Factory.

Endpoints verified 2026-10-04 against docs.tokenfactory.nebius.com and the Nebius Nemotron pages:
  * Token Factory global/EU : https://api.tokenfactory.nebius.com/v1/
  * us-central1 (serves nvidia/nemotron-3-super-120b-a12b): https://api.tokenfactory.us-central1.nebius.com/v1/
  * The AI Studio URL named in the brief (https://api.studio.nebius.com/v1/) is the pre-migration
    endpoint; Nebius announced the move to the Token Factory URLs above.
  * POST {base}/chat/completions, `Authorization: Bearer <NEBIUS_API_KEY>`.
  * response_format: {"type":"json_schema","json_schema":{name,schema,strict}} | {"type":"json_object"}.
Model availability/region pairing is configuration (NEBIUS_MODEL, NEBIUS_BASE_URL) and could NOT be
confirmed live (account billing-blocked at build time; see scripts/smoke_nebius.py).

The key is read ONLY from the NEBIUS_API_KEY environment variable (or the `api_key` argument used by
tests), is never logged, never part of exception text, never stored on the httpx client. Missing key =>
NotConfigured (clear message, no value).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Mapping
from typing import Any, Literal

import httpx
from contract import errors as ce
from contract.models import Message, Usage
from pydantic import BaseModel

from ..errors import NotConfigured
from ..redaction import get_logger, redact_text, register_secret
from .base import ModelBudget, ProviderBase, ProviderHealth, RawCompletion

log = get_logger("nebius")

DEFAULT_BASE_URL = "https://api.tokenfactory.us-central1.nebius.com/v1/"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
_TRANSIENT = {429, 500, 502, 503, 504}
_MODES = ("json_schema", "json_object", "prompt")


class NebiusProvider(ProviderBase):
    adapter_kind: Literal["nebius", "mock"] = "nebius"
    label = "nebius"

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        api_key: str | None = None,
        key_provider: Callable[[], str | None] | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float | None = None,
        temperature: float = 0.0,
        response_mode: str = "json_schema",
        http_retries: int = 2,
        max_repairs: int = 2,
        budget: ModelBudget | None = None,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
        allow_insecure_base_url: bool = False,
    ) -> None:
        super().__init__(max_repairs=max_repairs, budget=budget)
        self._env = os.environ if env is None else env
        self._explicit_key = api_key
        self._key_provider = key_provider  # e.g. credential-broker lease; wins over env
        register_secret(api_key)
        self.base_url = (base_url or self._env.get("NEBIUS_BASE_URL") or DEFAULT_BASE_URL).rstrip(
            "/"
        )
        if not self.base_url.startswith("https://") and not allow_insecure_base_url:
            raise ce.ConfigError(
                "NEBIUS_BASE_URL must use https (the key would travel in clear text)"
            )
        self.model_id = model or self._env.get("NEBIUS_MODEL") or DEFAULT_MODEL
        self.timeout_s = float(timeout_s or self._env.get("NEBIUS_TIMEOUT_S") or 30)
        self.temperature = temperature
        if response_mode not in _MODES:
            raise ce.ConfigError(f"response_mode must be one of {_MODES}")
        self.response_mode = response_mode
        self.http_retries = http_retries
        self._sleep = sleep
        self._client = client
        self._owns_client = client is None

    def __repr__(self) -> str:
        return f"NebiusProvider(model={self.model_id!r}, base_url={self.base_url!r}, key=<hidden>)"

    # -- config -----------------------------------------------------------------------------
    def is_configured(self) -> bool:
        return bool(self._resolve_key())

    def _resolve_key(self) -> str | None:
        key = self._explicit_key or (self._key_provider() if self._key_provider else None)
        key = key or self._env.get("NEBIUS_API_KEY")
        if key:
            register_secret(key)  # so it is redacted from any log/event even if it leaks upstream
        return key

    def _api_key(self) -> str:
        key = self._resolve_key()
        if not key:
            raise NotConfigured(
                "NEBIUS_API_KEY is not set: the Nebius provider cannot run (key not provided)"
            )
        return key

    def _http(self, timeout_s: float) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_s, connect=10.0), trust_env=False
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    # -- health -----------------------------------------------------------------------------
    async def health_check(self) -> ProviderHealth:
        """Cheap authenticated GET {base}/models. Never raises; reports ok=False with a reason."""
        if not self.is_configured():
            return ProviderHealth(
                ok=False, provider="nebius", model=self.model_id, detail="key not provided"
            )
        started = time.perf_counter()
        try:
            resp = await self._http(10).get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self._api_key()}"},
                timeout=10,
            )
            ok = resp.status_code == 200
            detail = "ok" if ok else f"HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            ok, detail = False, f"transport error: {type(exc).__name__}"
        return ProviderHealth(
            ok=ok,
            provider="nebius",
            model=self.model_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
            detail=redact_text(detail),
        )

    # -- completion -------------------------------------------------------------------------
    def _body(
        self, messages: list[Message], schema: type[BaseModel], max_tokens: int
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model_id,
            "messages": [m.model_dump() for m in messages],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if self.response_mode == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": False,
                },
            }
        elif self.response_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

    async def _complete_raw(
        self, messages: list[Message], schema: type[BaseModel], *, max_tokens: int, timeout_s: float
    ) -> RawCompletion:
        key = self._api_key()
        url = f"{self.base_url}/chat/completions"
        http_attempt = 0
        timeout_s = min(timeout_s, self.timeout_s) if timeout_s else self.timeout_s
        while True:
            body = self._body(messages, schema, max_tokens)
            try:
                resp = await self._http(timeout_s).post(
                    url,
                    json=body,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    timeout=timeout_s,
                )
            except httpx.TimeoutException:
                if http_attempt < self.http_retries:
                    http_attempt += 1
                    await self._sleep(min(2**http_attempt, 8))
                    continue
                raise ce.ModelUnavailable(f"model request timed out after {timeout_s}s") from None
            except httpx.HTTPError as exc:
                raise ce.ModelUnavailable(f"model transport error: {type(exc).__name__}") from None

            if resp.status_code in (400, 422) and self.response_mode != "prompt":
                nxt = _MODES[_MODES.index(self.response_mode) + 1]
                log.warning(
                    "response_format %s rejected (HTTP %s); falling back to %s",
                    self.response_mode,
                    resp.status_code,
                    nxt,
                )
                self.response_mode = nxt
                continue
            if resp.status_code in _TRANSIENT and http_attempt < self.http_retries:
                http_attempt += 1
                await self._sleep(min(2**http_attempt, 8))
                continue
            if resp.status_code >= 400:
                snippet = redact_text(resp.text, max_len=300)
                raise ce.ModelUnavailable(f"model HTTP {resp.status_code}: {snippet}")
            return self._parse(resp)

    def _parse(self, resp: httpx.Response) -> RawCompletion:
        try:
            data = resp.json()
            msg = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ce.ModelUnavailable("model returned a malformed chat completion") from None
        if msg.get("refusal"):
            raise ce.ModelUnavailable("model refused the request")
        content = msg.get("content")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str) or not content.strip():
            raise ce.ModelUnavailable("model returned empty content")
        u = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(u.get("prompt_tokens", 0) or 0),
            output_tokens=int(u.get("completion_tokens", 0) or 0),
        )
        return RawCompletion(
            text=content, usage=usage, model=str(data.get("model") or self.model_id)
        )
