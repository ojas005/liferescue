from pathlib import Path

import yaml
from openapi_spec_validator import validate

from contract import CONTRACT_VERSION
from contract.api_models import ERROR_CODES
from contract.openapi_gen import build_spec, render

SPEC = Path(__file__).resolve().parent.parent / "openapi.yaml"


def test_openapi_is_valid_3_1():
    spec = yaml.safe_load(SPEC.read_text())
    validate(spec)
    assert spec["openapi"].startswith("3.1") and spec["info"]["version"] == CONTRACT_VERSION


def test_openapi_has_no_drift_from_pydantic_models():
    assert SPEC.read_text() == render(), "openapi.yaml is stale: run `python -m contract.openapi_gen openapi.yaml`"


def test_required_endpoints_present():
    paths = build_spec()["paths"]
    assert set(paths) == {"/api/workflows", "/api/runs", "/api/runs/{run_id}", "/api/runs/{run_id}/timeline",
                          "/api/runs/{run_id}/approvals/{approval_id}", "/api/runs/{run_id}/cancel", "/api/health"}
    assert "get" in paths["/api/workflows"] and "post" in paths["/api/runs"] and "post" in paths["/api/runs/{run_id}/cancel"]


def test_all_refs_resolve_and_models_present():
    spec = build_spec()
    schemas = spec["components"]["schemas"]
    for name in ("RunResponse", "TimelinePage", "TimelineEvent", "Approval", "RunRecord", "WorkflowSummary", "CreateRunRequest", "ErrorResponse"):
        assert name in schemas
    text = yaml.safe_dump(spec)
    import re
    for ref in set(re.findall(r"#/components/schemas/(\w+)", text)):
        assert ref in schemas, ref
    assert set(ERROR_CODES.values()) <= {404, 409, 422}
