"""The app's generated OpenAPI must match packages/contract/openapi.yaml (paths, methods, operation ids, response codes,
referenced model names, and the properties/required of every contract model)."""

from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from openapi_spec_validator import validate

from app.main import create_app
from app.settings import Settings

CONTRACT_YAML = Path(__file__).resolve().parents[3] / "packages" / "contract" / "openapi.yaml"
METHODS = ("get", "post", "put", "delete", "patch")


def _app_spec() -> dict[str, Any]:
    app: FastAPI = create_app(
        Settings(_env_file=None, liferescue_env="test", model_adapter="mock", database_url="sqlite://")
    )
    return app.openapi()


def _refs(node: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                out.add(v.rsplit("/", 1)[-1])
            else:
                out |= _refs(v)
    elif isinstance(node, list):
        for v in node:
            out |= _refs(v)
    return out


def test_app_spec_is_valid_openapi() -> None:
    validate(_app_spec())


def test_paths_methods_operations_and_responses_match_contract() -> None:
    contract = yaml.safe_load(CONTRACT_YAML.read_text())
    app = _app_spec()
    assert contract["info"]["version"] == app["info"]["version"] == "0.1.0"
    assert set(contract["paths"]) == set(app["paths"]), "app must expose exactly the contract paths"
    for path, ops in contract["paths"].items():
        for method in (m for m in METHODS if m in ops):
            c_op, a_op = ops[method], app["paths"][path][method]
            assert c_op["operationId"] == a_op["operationId"], (path, method)
            assert set(c_op["responses"]) <= set(a_op["responses"]), (path, method, "missing status codes")
            for code, resp in c_op["responses"].items():
                assert _refs(resp) == _refs(a_op["responses"][code]), (path, method, code)
            assert _refs(c_op.get("requestBody", {})) == _refs(a_op.get("requestBody", {})), (path, method)


def test_contract_models_have_same_fields() -> None:
    contract = yaml.safe_load(CONTRACT_YAML.read_text())["components"]["schemas"]
    app = _app_spec()["components"]["schemas"]
    for name in (
        "WorkflowSummary",
        "CreateRunRequest",
        "RunResponse",
        "TimelinePage",
        "ApprovalDecisionRequest",
        "CancelRunRequest",
        "ErrorResponse",
        "HealthResponse",
        "RunRecord",
        "Approval",
        "TimelineEvent",
    ):
        assert name in app, name
        assert set(contract[name]["properties"]) == set(app[name]["properties"]), name
        assert set(contract[name].get("required", [])) == set(app[name].get("required", [])), name
