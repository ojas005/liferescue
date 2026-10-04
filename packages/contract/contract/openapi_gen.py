"""Generates openapi.yaml (OpenAPI 3.1.0) from the pydantic models. `python -m contract.openapi_gen [path]` rewrites the file.

FastAPI's own generated schema in apps/api must stay compatible (the contract test in tests/ compares paths and model names)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic.json_schema import models_json_schema

from . import CONTRACT_VERSION
from .api_models import (
    ApprovalDecisionRequest, CancelRunRequest, CreateRunRequest, ErrorResponse, HealthResponse, RunResponse, TimelinePage, WorkflowSummary,
)

MODELS = [WorkflowSummary, CreateRunRequest, RunResponse, TimelinePage, ApprovalDecisionRequest, CancelRunRequest, ErrorResponse, HealthResponse]


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _json(name: str) -> dict[str, Any]:
    return {"application/json": {"schema": _ref(name)}}


def _err(desc: str) -> dict[str, Any]:
    return {"description": desc, "content": _json("ErrorResponse")}


def build_spec() -> dict[str, Any]:
    pairs: list[tuple[Any, Any]] = [(m, "serialization") for m in MODELS]
    _, top = models_json_schema(pairs, ref_template="#/components/schemas/{model}")
    schemas = top.get("$defs", {})
    run_id = {"name": "run_id", "in": "path", "required": True, "schema": {"type": "string"}}
    e404, e409, e422 = _err("Not found"), _err("Conflict (illegal transition, approval not pending, concurrent change)"), _err("Validation error")
    return {
        "openapi": "3.1.0",
        "info": {"title": "LifeRescue Run API", "version": CONTRACT_VERSION,
                 "description": "One generic run API for every workflow. No authentication in the sprint (PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL)."},
        "servers": [{"url": "http://localhost:8000"}],
        "paths": {
            "/api/workflows": {"get": {"operationId": "listWorkflows", "summary": "List available workflows",
                "responses": {"200": {"description": "Workflows", "content": {"application/json": {"schema": {"type": "array", "items": _ref("WorkflowSummary")}}}}}}},
            "/api/runs": {"post": {"operationId": "createRun", "summary": "Create a run; the runtime starts at INTENT and advances until done or blocked on approval",
                "requestBody": {"required": True, "content": _json("CreateRunRequest")},
                "responses": {"201": {"description": "Run created (snapshot at response time)", "content": _json("RunResponse")}, "404": e404, "422": e422}}},
            "/api/runs/{run_id}": {"get": {"operationId": "getRun", "summary": "Get a run snapshot with its approvals", "parameters": [run_id],
                "responses": {"200": {"description": "Run", "content": _json("RunResponse")}, "404": e404}}},
            "/api/runs/{run_id}/timeline": {"get": {"operationId": "getTimeline",
                "summary": "Poll timeline events with seq > after_seq (polling chosen over SSE; PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL)",
                "parameters": [run_id,
                               {"name": "after_seq", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 0, "default": 0}},
                               {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200}}],
                "responses": {"200": {"description": "Events (payloads redacted)", "content": _json("TimelinePage")}, "404": e404}}},
            "/api/runs/{run_id}/approvals/{approval_id}": {"post": {"operationId": "decideApproval",
                "summary": "Approve or deny one pending approval (bound to the action digest, single use)",
                "parameters": [run_id, {"name": "approval_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": {"required": True, "content": _json("ApprovalDecisionRequest")},
                "responses": {"200": {"description": "Run after the decision (may have advanced)", "content": _json("RunResponse")}, "404": e404, "409": e409, "422": e422}}},
            "/api/runs/{run_id}/cancel": {"post": {"operationId": "cancelRun", "summary": "Cancel a run (only before ACTION starts)",
                "parameters": [run_id], "requestBody": {"required": False, "content": _json("CancelRunRequest")},
                "responses": {"200": {"description": "Cancelled run", "content": _json("RunResponse")}, "404": e404, "409": e409}}},
            "/api/health": {"get": {"operationId": "health", "summary": "Liveness and contract/model-adapter info (PROPOSED ASSUMPTION)",
                "responses": {"200": {"description": "OK", "content": _json("HealthResponse")}}}},
        },
        "components": {"schemas": schemas},
    }


def render() -> str:
    out: str = yaml.safe_dump(build_spec(), sort_keys=False, allow_unicode=True, width=120)
    return out


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.yaml")
    out.write_text(render())
    print(f"wrote {out}")
