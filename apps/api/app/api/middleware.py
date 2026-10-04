"""Pure-ASGI middleware: request size limit (U4), security headers (A5)."""

from __future__ import annotations

from contract.api_models import ErrorResponse
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _too_large() -> JSONResponse:
    body = ErrorResponse(error="payload_too_large", message="Request body is too large.")
    return JSONResponse(status_code=413, content=body.model_dump(mode="json"))


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > self.max_bytes:
                        await _too_large()(scope, receive, send)
                        return
                except ValueError:
                    await _too_large()(scope, receive, send)
                    return
        seen = 0

        class _Exceeded(Exception):
            pass

        async def limited() -> Message:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_bytes:
                    raise _Exceeded
            return msg

        try:
            await self.app(scope, limited, send)
        except _Exceeded:
            await _too_large()(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
