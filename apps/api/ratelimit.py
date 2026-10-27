"""Per-client-IP rate limiting for cost/abuse-sensitive routes (KAN-50).

Fixed-window counters are stored in SQLite, so they are shared by every worker process that
uses the same database file and they survive a worker restart. With db_path=":memory:" (tests)
the store is a private per-process in-memory database.

Client identity is the socket peer. Proxy headers are used ONLY when trust_proxy is set: first
CF-Connecting-IP (set by Cloudflare in front of Render), else the RIGHTMOST X-Forwarded-For hop: that is the address appended by the trusted proxy (Render
appends the real client IP). Left-hand hops are client-supplied and are ignored, as is
X-Real-IP. Over-limit requests get 429 with a generic message.
"""

from __future__ import annotations

import ipaddress
import logging
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from packages.storage.rate_limit import (
    GLOBAL_AI_KEY,
    RateLimiter,
    RateLimitUnavailable,
    store_path_for,
)

__all__ = [
    "GLOBAL_AI_KEY",
    "RateLimitMiddleware",
    "RateLimitUnavailable",
    "RateLimiter",
    "client_ip",
    "is_limited",
    "store_path_for",
]

# POST routes that spend model credits or mutate shared demo state.
LIMITED_ROUTES = (
    re.compile(r"^/incidents/?$"),
    re.compile(r"^/incidents/[^/]+/analyze/?$"),
    re.compile(r"^/demo/scenarios/[^/]+/run/?$"),
    re.compile(r"^/demo/reset/?$"),
)

logger = logging.getLogger(__name__)


def is_limited(method: str, path: str) -> bool:
    return method == "POST" and any(r.match(path) for r in LIMITED_ROUTES)


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip_with_source(request: Request, trust_proxy: bool) -> tuple[str, str]:
    peer = request.client.host if request.client else "unknown"
    if trust_proxy:
        # Render serves onrender.com through Cloudflare, which sets CF-Connecting-IP to the real
        # client and overwrites any client-supplied value. The rightmost XFF hop there is a
        # proxy address that varies per request, so it cannot be the bucket key.
        cf = _valid_ip(request.headers.get("cf-connecting-ip", ""))
        if cf:
            return cf, "cf-connecting-ip"
        xff = request.headers.get("x-forwarded-for", "")
        hops = [h for h in (p.strip() for p in xff.split(",")) if h]
        if hops:
            ip = _valid_ip(hops[-1])  # rightmost = appended by the trusted proxy
            if ip:
                return ip, "xff-rightmost"
    return peer, "peer"


def client_ip(request: Request, trust_proxy: bool) -> str:
    return client_ip_with_source(request, trust_proxy)[0]


_DIAG_REMAINING = 5


def _log_key_diagnostics(request: Request, trust_proxy: bool, source: str) -> None:
    """Log the SHAPE of proxy headers for the first few limited requests per process.

    No IP addresses or header values are logged: only which headers exist, the XFF hop count
    and which source produced the bucket key, so the deployment's proxy chain can be checked.
    """
    global _DIAG_REMAINING
    if _DIAG_REMAINING <= 0:
        return
    _DIAG_REMAINING -= 1
    h = request.headers
    xff = h.get("x-forwarded-for", "")
    logger.warning(  # WARNING so it shows under uvicorn defaults; no PII
        "rate-limit key diag: trust_proxy=%s source=%s cf_connecting_ip=%s "
        "true_client_ip=%s x_real_ip=%s xff_hops=%d",
        trust_proxy,
        source,
        "cf-connecting-ip" in h,
        "true-client-ip" in h,
        "x-real-ip" in h,
        len([p for p in xff.split(",") if p.strip()]),
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter, trust_proxy: bool = False):
        super().__init__(app)
        self.limiter = limiter
        self.trust_proxy = trust_proxy

    async def dispatch(self, request: Request, call_next) -> Response:
        if self.limiter.limit > 0 and is_limited(request.method, request.url.path):
            try:
                ip, source = client_ip_with_source(request, self.trust_proxy)
                _log_key_diagnostics(request, self.trust_proxy, source)
                ok, retry = self.limiter.allow("ip:" + ip)
            except RateLimitUnavailable as err:
                # FAIL CLOSED: an unreadable limiter must not become an unlimited spend path.
                logger.warning("rate limiter unavailable (%s); returning 503", err)
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "ServiceUnavailable",
                        "detail": "Temporarily unavailable, try again.",
                    },
                    headers={"Retry-After": "5"},
                )
            if not ok:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "TooManyRequests",
                        "detail": "Rate limit exceeded. Please wait and try again.",
                    },
                    headers={"Retry-After": str(retry)},
                )
        return await call_next(request)
