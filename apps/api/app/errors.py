"""Error mapping: contract exceptions -> contract ``ErrorResponse`` {error, message}. Messages are fixed/safe:
never submitted values, never raw exception text (SECURITY A5)."""

from __future__ import annotations

import logging

from contract import errors as ce
from contract.api_models import ERROR_CODES, ErrorResponse
from contract.validation import InvalidInput
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("liferescue.api")


class ApiError(Exception):
    """Raised by routers for conditions that have no contract exception (code must be a stable machine code)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status_code, self.code, self.message = status_code, code, message


# Contract exception -> (stable error code from ERROR_CODES, safe message). ApprovalError/InvalidInput carry
# non-contract `.code` values ("approval_error"/"contract_error"), so they are mapped explicitly here.
_MAP: list[tuple[type[Exception], str, str]] = [
    (ce.WorkflowNotFound, "workflow_not_found", "Unknown workflow."),
    (ce.RunNotFound, "run_not_found", "Run not found."),
    (InvalidInput, "invalid_input", "Run input does not match the workflow input schema."),
    (
        ce.IllegalTransition,
        "illegal_transition",
        "That transition is not allowed in the run's current state.",
    ),
    (ce.GuardFailed, "guard_failed", "A transition guard failed."),
    (ce.ConcurrentModification, "concurrent_modification", "The run was modified concurrently; retry."),
    (
        ce.ApprovalError,
        "approval_invalid",
        "The approval cannot be used (not pending, expired, used or mismatched).",
    ),
]


class ApprovalNotFound(Exception):
    pass


def _resp(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content=ErrorResponse(error=code, message=message).model_dump(mode="json")
    )


def status_for(code: str) -> int:
    return ERROR_CODES.get(code, 500)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _resp(exc.status_code, exc.code, exc.message)

    @app.exception_handler(ApprovalNotFound)
    async def _ap_nf(request: Request, exc: ApprovalNotFound) -> JSONResponse:
        return _resp(404, "approval_not_found", "Approval not found for this run.")

    @app.exception_handler(ce.ContractError)
    async def _contract_error(request: Request, exc: ce.ContractError) -> JSONResponse:
        for cls, code, message in _MAP:
            if isinstance(exc, cls):
                return _resp(status_for(code), code, message)
        log.error("unmapped_contract_error", extra={"exc_type": type(exc).__name__})
        return _resp(500, "internal_error", "Internal server error.")  # fail closed, no detail

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}
        return _resp(
            exc.status_code, codes.get(exc.status_code, "http_error"), "Request could not be processed."
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Only location + error type; the submitted value (`input`) is never echoed (A5).
        locs = "; ".join(
            f"{'.'.join(str(x) for x in e.get('loc', ()))} ({e.get('type', 'invalid')})"
            for e in exc.errors()[:10]
        )
        return _resp(422, "invalid_input", f"Request validation failed: {locs}")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", extra={"exc_type": type(exc).__name__})
        return _resp(500, "internal_error", "Internal server error.")
