"""Constrained Tavily research tool for LifeRescue (KAN-50).

One explicit, bounded tool: POST https://api.tavily.com/search with a query built ONLY from the
coarse incident category and urgency (no names, phones, locations or free text from the user).

Results are UNTRUSTED EVIDENCE: they are reduced to title / url / short snippet, truncated, shown to
the user as "Research evidence (Tavily, live)", and are never fed to the model, never used as
instructions, and never change the safety policy, risk assessment or response plan.

If TAVILY_API_KEY is missing or the call fails, the step is skipped and labelled
"research unavailable: <reason>". Results are never fabricated.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from packages.domain.models import utcnow

logger = logging.getLogger("liferescue.research")

TAVILY_ENDPOINT = "https://api.tavily.com/search"
LIVE_LABEL = "Research evidence (Tavily, live)"
MAX_RESULTS = 3
TIMEOUT_S = 8.0
MAX_ATTEMPTS = 1  # Exactly 1 bounded attempt per submission; no unbounded retries
QUERY_MAX = 120
TITLE_MAX = 120
URL_MAX = 300
SNIPPET_MAX = 240

_SAFE_TOKEN = re.compile(r"[^a-z0-9 _-]")
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")


def unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "label": f"research unavailable: {reason}",
        "results": [],
    }


def _extract_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        host = host.removeprefix("www.")
        return host or "external-source"
    except Exception:  # noqa: BLE001
        return "external-source"


def _relevance_for_category(category: str) -> str:
    cat = str(category or "").lower()
    if any(k in cat for k in ("cardiac", "heart", "chest", "medical", "breathing")):
        return "Clinical first aid and emergency response protocol reference"
    if any(k in cat for k in ("accident", "collision", "vehicle", "crash", "trauma")):
        return "Roadside collision safety and trauma response reference"
    if any(k in cat for k in ("fire", "wildfire", "smoke", "burn")):
        return "Fire containment, evacuation advisory, and burn safety reference"
    if any(k in cat for k in ("hazmat", "chemical", "spill", "gas")):
        return "Hazardous materials isolation and exposure safety reference"
    if any(k in cat for k in ("flood", "storm", "water", "weather")):
        return "Severe weather and flood evacuation preparedness reference"
    return "Public safety emergency protocol reference"


def build_query(category: str, urgency: str) -> str:
    """Coarse, PII-free query: only the category/urgency enums, sanitized and length-capped."""
    cat = _SAFE_TOKEN.sub("", str(category or "general").lower().replace("_", " "))[
        :40
    ].strip()
    urg = _SAFE_TOKEN.sub("", str(urgency or "").lower())[:20].strip()
    q = f"first aid safety guidance {cat or 'general'} emergency {urg}".strip()
    return q[:QUERY_MAX]


def _clean(value: Any, limit: int) -> str:
    text = _CTRL.sub(" ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class TavilyResearchTool:
    """Explicit constrained tool around the Tavily search API."""

    def __init__(
        self, api_key: str | None = None, transport: httpx.BaseTransport | None = None
    ):
        self._api_key = (
            api_key if api_key is not None else os.environ.get("TAVILY_API_KEY", "")
        )
        self._transport = transport

    def search(self, category: str, urgency: str) -> dict[str, Any]:
        if not self._api_key:
            return unavailable("TAVILY_API_KEY not configured")
        query = build_query(category, urgency)
        body = {
            "query": query,
            "search_depth": "basic",
            "max_results": MAX_RESULTS,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        kwargs: dict[str, Any] = {"timeout": httpx.Timeout(TIMEOUT_S)}
        if self._transport is not None:
            kwargs["transport"] = self._transport

        reason = "unknown error"
        try:
            with httpx.Client(**kwargs) as client:
                resp = client.post(TAVILY_ENDPOINT, json=body, headers=headers)
            if resp.status_code == 429:
                return unavailable("rate limit (http 429)")
            if resp.status_code != 200:
                return unavailable(f"http {resp.status_code}")
            return self._parse(resp, query, category=category)
        except httpx.TimeoutException:
            reason = "timeout"
        except httpx.HTTPError as err:
            reason = f"network error ({type(err).__name__})"
        except Exception as err:  # noqa: BLE001 - research must never break triage
            reason = f"unexpected error ({type(err).__name__})"
        logger.warning("Tavily research failed: %s", reason)
        return unavailable(reason)

    @staticmethod
    def _parse(resp: httpx.Response, query: str, category: str = "") -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError:
            return unavailable("malformed response")
        raw = data.get("results") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return unavailable("malformed response")
        results = []
        for item in raw[:MAX_RESULTS]:
            if not isinstance(item, dict):
                continue
            url = _clean(item.get("url"), URL_MAX)
            if not url.startswith(("https://", "http://")):
                continue
            title = _clean(item.get("title"), TITLE_MAX)
            snippet = _clean(item.get("content"), SNIPPET_MAX)
            published = item.get("published_date")
            domain = _extract_domain(url)
            score = item.get("score")
            score_val = (
                round(float(score), 2) if isinstance(score, (int, float)) else None
            )

            results.append(
                {
                    "title": title or f"External reference ({domain})",
                    "url": url,
                    "snippet": snippet,
                    "domain": domain,
                    "published_date": _clean(published, 40) if published else None,
                    "relevance_note": _relevance_for_category(category),
                    "score": score_val,
                }
            )
        if not results:
            return unavailable("no results")
        return {
            "status": "live",
            "label": LIVE_LABEL,
            "query": query,
            "retrieved_at": utcnow().isoformat(),
            "results": results,
            "note": "Untrusted third-party evidence for reference only; it does not change triage, safety policy or the response plan.",
            "disclaimer": "External search results are unverified third-party references. They do not constitute official emergency instructions and never override deterministic safety policies.",
        }
