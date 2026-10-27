"""In-process per-client-IP rate limiting for cost/abuse-sensitive routes (KAN-50).

Fixed-window counters kept in memory, per app instance (not shared across replicas/restarts).
Client IP is the socket peer; the first X-Forwarded-For hop is used ONLY when trust_proxy is set
(e.g. behind Render's proxy). Over-limit requests get 429 with a generic message.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# POST routes that spend model credits or mutate shared demo state.
LIMITED_ROUTES = (
    re.compile(r"^/incidents/?$"),
    re.compile(r"^/incidents/[^/]+/analyze/?$"),
    re.compile(r"^/demo/scenarios/[^/]+/run/?$"),
    re.compile(r"^/demo/reset/?$"),
)
_MAX_CLIENTS = 10_000


def is_limited(method: str, path: str) -> bool:
    return method == "POST" and any(r.match(path) for r in LIMITED_ROUTES)


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        xff = request.headers.get("x-forwarded-for", "")
        first = xff.split(",", 1)[0].strip()
        if first:
            return first[:64]
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(
        self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic
    ):
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= self.window_s:
                start, count = now, 0
            if count >= self.limit:
                return False, max(1, int(self.window_s - (now - start)) + 1)
            if len(self._hits) >= _MAX_CLIENTS and key not in self._hits:
                self._hits = {
                    k: v for k, v in self._hits.items() if now - v[0] < self.window_s
                }
            self._hits[key] = (start, count + 1)
            return True, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter, trust_proxy: bool = False):
        super().__init__(app)
        self.limiter = limiter
        self.trust_proxy = trust_proxy

    async def dispatch(self, request: Request, call_next) -> Response:
        if self.limiter.limit > 0 and is_limited(request.method, request.url.path):
            ok, retry = self.limiter.allow(client_ip(request, self.trust_proxy))
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
