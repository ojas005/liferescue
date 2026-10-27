"""Middleware and error sanitization for LifeRescue API."""

from __future__ import annotations

import logging
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from packages.secrets.guards import RedactingLogFilter
from packages.secrets.redaction import PatternSet, Redactor

logger = logging.getLogger("liferescue.api")


def setup_secure_logging() -> None:
    """Attach KAN-45 RedactingLogFilter to root and application loggers."""
    redactor = Redactor(patterns=PatternSet.load())
    log_filter = RedactingLogFilter(redactor)

    root_logger = logging.getLogger()
    root_logger.addFilter(log_filter)

    for handler in root_logger.handlers:
        handler.addFilter(log_filter)

    app_logger = logging.getLogger("liferescue")
    app_logger.addFilter(log_filter)

    # SEC-09: uvicorn's access/error loggers log directly (request paths may carry secrets)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        if log_filter not in lg.filters:
            lg.addFilter(log_filter)
        for handler in lg.handlers:
            handler.addFilter(log_filter)


class SecurityAndCorrelationMiddleware(BaseHTTPMiddleware):
    """Generates request correlation IDs and ensures safe HTTP header handling."""

    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"
        request.state.request_id = req_id

        start_time = time.time()
        try:
            response = await call_next(request)
            elapsed_ms = int((time.time() - start_time) * 1000)
            response.headers["X-Request-ID"] = req_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"

            # Log without raw body
            logger.info(
                "%s %s -> %d (%dms) [req_id=%s]",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
                req_id,
            )
            return response
        except Exception as exc:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "Unhandled API error on %s [req_id=%s]: %s",
                request.url.path,
                req_id,
                exc,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "InternalServerError",
                    "detail": "An unexpected error occurred. Details have been safely logged.",
                    "request_id": req_id,
                },
                headers={
                    "X-Request-ID": req_id,
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                },
            )
