"""SEC-04: optional shared demo access token (X-Demo-Token).

- Required (startup fails closed) whenever the server binds to a non-loopback host.
- When set, every API route except /health, / and /static/* requires it (constant-time compare).
- The token is never logged, echoed, or included in error bodies.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os

from starlette.requests import Request
from starlette.responses import JSONResponse

from packages.secrets.guards import redact_record_message

TOKEN_HEADER = "X-Demo-Token"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
PUBLIC_PATHS = {"/health", "/", "/favicon.ico"}
PUBLIC_PREFIXES = ("/static/",)

logger = logging.getLogger("liferescue.access")


class InsecureBindError(RuntimeError):
    """Raised at startup when binding off-loopback without DEMO_ACCESS_TOKEN."""


def _clean_token_str(val: str | None) -> str | None:
    """Normalize a token string: strip whitespace, newlines, and surrounding quotes."""
    if not val:
        return None
    s = str(val).strip().strip("\r\n\t")
    # Repeatedly strip matched enclosing quotation marks
    quote_pairs = [
        ('"', '"'),
        ("'", "'"),
        ("“", "”"),
        ("‘", "’"),
        ("`", "`"),
    ]
    changed = True
    while changed and len(s) >= 2:
        changed = False
        for q_start, q_end in quote_pairs:
            if s.startswith(q_start) and s.endswith(q_end):
                s = s[len(q_start) : -len(q_end)].strip()
                changed = True
                break
    return s if s else None


def _clean_token_bytes(val: bytes | str | None) -> bytes | None:
    """Normalize token to cleaned UTF-8 bytes."""
    if val is None:
        return None
    if isinstance(val, bytes):
        try:
            s_val = val.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - fail-safe boundary: must never propagate
            return None
    else:
        s_val = str(val)
    cleaned = _clean_token_str(s_val)
    return cleaned.encode("utf-8") if cleaned else None


def token_matches(configured: bytes | None, supplied: bytes | None) -> bool:
    """Constant-time token comparison supporting raw and cleaned representations."""
    if not configured or not supplied:
        return False
    # 1. Exact raw comparison
    if hmac.compare_digest(configured, supplied):
        return True
    # 2. Cleaned comparison (outer quotes, whitespace, and newlines normalized)
    clean_c = _clean_token_bytes(configured)
    clean_s = _clean_token_bytes(supplied)
    return bool(clean_c and clean_s and hmac.compare_digest(clean_c, clean_s))


def _extract_token_from_request(request: Request) -> tuple[str, str]:
    """Extract demo token and source name from request. Never exposes the value in logs."""
    # 1. Standard custom header: X-Demo-Token
    h_token = request.headers.get(TOKEN_HEADER)
    if h_token:
        return h_token.strip(), "header:X-Demo-Token"
    # 2. Standard Authorization header: Bearer <token>
    auth = request.headers.get("Authorization")
    if auth and auth.strip().lower().startswith("bearer "):
        return auth.strip()[7:].strip(), "header:Authorization"
    # 3. Query parameter: token or demo_token
    q_token = request.query_params.get("token") or request.query_params.get(
        "demo_token"
    )
    if q_token:
        return q_token.strip(), "query_param"
    return "", "none"


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
    has_token = bool(_clean_token_str(token))
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
        self._targets: list[str] = []
        raw = (token or "").strip()
        if len(raw) >= 4:
            self._targets.append(raw)
        clean = _clean_token_str(token)
        if clean and len(clean) >= 4 and clean not in self._targets:
            self._targets.append(clean)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - fail-safe boundary: must never propagate
            return True
        for tgt in self._targets:
            if tgt in msg:
                redact_record_message(
                    record,
                    msg,
                    lambda t, _tgt=tgt: t.replace(_tgt, "[REDACTED:demo_token]"),
                )
                msg = record.getMessage()
        return True


class DemoTokenMiddleware:
    """Pure ASGI middleware so it applies before routing."""

    def __init__(self, app, token: str | None) -> None:
        self.app = app
        self._token = (token or "").strip().encode() or None

    def _get_configured_token(self) -> bytes | None:
        """Resolve configured token dynamically: os.environ first, then startup cache."""
        env_token = os.environ.get("DEMO_ACCESS_TOKEN")
        if env_token is not None:
            stripped = env_token.strip().encode("utf-8")
            if stripped:
                return stripped
        return self._token

    @staticmethod
    def _public(path: str) -> bool:
        return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        configured = self._get_configured_token()
        if configured is None:
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

        supplied_str, source = _extract_token_from_request(request)
        supplied = supplied_str.encode("utf-8") if supplied_str else None

        if not supplied or not token_matches(configured, supplied):
            logger.warning(
                "Demo auth rejected: method=%s path=%s token_configured=%s header_present=%s auth_source=%s",
                request.method,
                request.url.path,
                bool(configured),
                bool(request.headers.get(TOKEN_HEADER)),
                source,
            )
            return await self._deny(
                scope, receive, send, 401, "Missing or invalid demo access token."
            )

        logger.info(
            "Demo auth verified: method=%s path=%s auth_source=%s",
            request.method,
            request.url.path,
            source,
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
