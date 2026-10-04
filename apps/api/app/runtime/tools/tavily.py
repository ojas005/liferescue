"""Tavily research provider (ResearchProvider port from the platform contract; checklist S6).

* Key ONLY from env TAVILY_API_KEY (sent in the Authorization header, server side only).
* Results are untrusted data: capped to <= 5 results and a snippet length cap.
* The query is masked (cards, Aadhaar, PAN, OTP/PIN/CVV, phone numbers, e-mails) before leaving.
* Daily cap (TAVILY_DAILY_CAP, default 200 per process/UTC-day); per-run cap (5) is in the engine.
HTTP client is injectable for tests.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime

import httpx
from contract.interfaces import SearchQuery, SearchResult

from ..errors import FetchFailed, LimitReached, NotConfigured
from ..redaction import mask_pii, redact_text, register_secret

TAVILY_URL = "https://api.tavily.com/search"
MAX_RESULTS = 5
SNIPPET_CHARS = 1000


class TavilyProvider:
    """Implements contract `ResearchProvider`."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
        daily_cap: int | None = None,
    ) -> None:
        self._env = os.environ if env is None else env
        self._client = client
        self.timeout_s = timeout_s
        self.daily_cap = (
            daily_cap if daily_cap is not None else int(self._env.get("TAVILY_DAILY_CAP", "200"))
        )
        self._day = ""
        self._count = 0

    def __repr__(self) -> str:
        return "TavilyProvider(key=<hidden>)"

    def _key(self) -> str:
        key = self._env.get("TAVILY_API_KEY")
        if not key:
            raise NotConfigured("TAVILY_API_KEY is not set (key not provided)")
        register_secret(
            key
        )  # redacted from any error/log even if injected rather than in os.environ
        return key

    def _count_call(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._day:
            self._day, self._count = today, 0
        if self._count >= self.daily_cap:
            raise LimitReached(f"daily Tavily cap reached ({self.daily_cap})")
        self._count += 1

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        key = self._key()
        self._count_call()
        q = mask_pii(query.query, include_contacts=True)[:400]
        body: dict[str, object] = {
            "query": q,
            "max_results": min(max(query.max_results, 1), MAX_RESULTS),
            "search_depth": "basic",
            "include_answer": False,
        }
        if query.allowed_domains:
            body["include_domains"] = query.allowed_domains[:10]
        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_s, trust_env=False)
        try:
            resp = await client.post(
                TAVILY_URL,
                json=body,
                headers={"Authorization": f"Bearer {key}"},
                timeout=self.timeout_s,
            )
        except httpx.TimeoutException:
            raise FetchFailed("tavily request timed out") from None
        except httpx.HTTPError as exc:
            raise FetchFailed(f"tavily transport error: {type(exc).__name__}") from None
        finally:
            if owns:
                await client.aclose()
        if resp.status_code >= 400:
            raise FetchFailed(
                f"tavily HTTP {resp.status_code}: {redact_text(resp.text, max_len=200)}"
            )
        try:
            raw = resp.json().get("results", [])
        except ValueError:
            raise FetchFailed("tavily returned non-JSON") from None
        out: list[SearchResult] = []
        for r in raw[:MAX_RESULTS]:
            if not isinstance(r, dict):
                continue
            score = r.get("score")
            out.append(
                SearchResult(
                    title=str(r.get("title", ""))[:200],
                    url=str(r.get("url", ""))[:500],
                    snippet=str(r.get("content", ""))[:SNIPPET_CHARS],
                    score=float(score) if isinstance(score, int | float) else None,
                )
            )
        return out
