"""SEC-04: optional shared demo access token (X-Demo-Token).

- Required (startup fails closed) whenever the server binds to a non-loopback host.
- When set, every API route except /health, / and /static/* requires it (constant-time compare).
- The token is never logged, echoed, or included in error bodies.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from packages.secrets.guards import redact_record_message

TOKEN_HEADER = "X-Demo-Token"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
PUBLIC_PATHS = {"/health", "/", "/favicon.ico"}
PUBLIC_PREFIXES = ("/static/",)


class InsecureBindError(RuntimeError):
    """Raised at startup when binding off-loopback without DEMO_ACCESS_TOKEN."""


def is_loopback(host: str | None) -> bool:
    if not host:
        return True
    h = host.strip().strip("[]").lower()
    if h in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


TUNNEL_WARNING = (
    "WARNING: access gate is OPEN. Any tunnel/proxy/public exposure (ngrok, cloudflared, ssh -R, "
    "port-forward) makes localhost reachable from the internet: set DEMO_ACCESS_TOKEN and "
    "DEMO_REQUIRE_TOKEN=1 first."
)


def enforce_bind_policy(
    host: str | None, token: str | None, require_token: bool = False
) -> None:
    has_token = bool(token and token.strip())
    if require_token and not has_token:
        raise InsecureBindError(
            "Refusing to start: DEMO_REQUIRE_TOKEN=1 but DEMO_ACCESS_TOKEN is not set. "
            "Set DEMO_ACCESS_TOKEN in the environment (never commit it)."
        )
    if not is_loopback(host) and not has_token:
        raise InsecureBindError(
            f"Refusing to start: host {host!r} is not localhost and DEMO_ACCESS_TOKEN is not set. "
            "Set DEMO_ACCESS_TOKEN in the environment (never commit it) or bind to 127.0.0.1."
        )


class TokenLogFilter(logging.Filter):
    """Replaces the literal token value anywhere in a log record message."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._t = token

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - fail-safe boundary: must never propagate
            return True
        if self._t in msg:
            # N-04: keep record.args (uvicorn.access unpacks them); redact element-wise.
            redact_record_message(
                record, msg, lambda t: t.replace(self._t, "[REDACTED:demo_token]")
            )
        return True


class DemoTokenMiddleware:
    """Pure ASGI middleware so it applies before routing."""

    def __init__(self, app, token: str | None) -> None:
        self.app = app
        self._token = (token or "").strip().encode() or None

    @staticmethod
    def _public(path: str) -> bool:
        return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        if self._token is None:
            # Defence in depth for `uvicorn --host 0.0.0.0` bypassing run.py: refuse off-loopback serving.
            server = scope.get("server") or (None, None)
            if (
                server[0]
                and _is_ip(server[0])
                and not is_loopback(server[0])
                and not self._public(request.url.path)
            ):
                return await self._deny(
                    scope,
                    receive,
                    send,
                    503,
                    "Server is not bound to localhost and no DEMO_ACCESS_TOKEN is configured.",
                )
            return await self.app(scope, receive, send)
        if request.method == "OPTIONS" or self._public(request.url.path):
            return await self.app(scope, receive, send)
        supplied = request.headers.get(TOKEN_HEADER, "").strip().encode()
        if not supplied or not hmac.compare_digest(supplied, self._token):
            return await self._deny(
                scope, receive, send, 401, "Missing or invalid demo access token."
            )
        return await self.app(scope, receive, send)

    @staticmethod
    async def _deny(scope, receive, send, status: int, detail: str):
        resp = JSONResponse(
            status_code=status,
            content={
                "error": "Unauthorized" if status == 401 else "ServiceUnavailable",
                "detail": detail,
            },
            headers={"WWW-Authenticate": TOKEN_HEADER} if status == 401 else None,
        )
        await resp(scope, receive, send)
