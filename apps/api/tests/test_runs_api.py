"""Contract endpoints with the placeholder runtime (no engine wired): creation, snapshot, timeline, cancel, limits."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.conftest import VEHICLE


def test_list_workflows_returns_contract_summaries(client: TestClient) -> None:
    r = client.get("/api/workflows")
    assert r.status_code == 200
    ids = {w["workflow_id"] for w in r.json()}
    assert ids == {"vehicle_breakdown", "scam_investigation", "life_admin"}
    for w in r.json():
        assert set(w) == {"workflow_id", "version", "title", "description", "input_schema"}
        assert w["input_schema"]["type"] == "object"


def test_create_get_and_timeline(client: TestClient) -> None:
    r = client.post("/api/runs", json=VEHICLE)
    assert r.status_code == 201
    body = r.json()
    run = body["run"]
    uuid.UUID(run["run_id"])
    assert run["state"] == "intent" and run["owner"] == "demo-user" and run["contract_version"] == "0.1.0"
    assert body["approvals"] == [] and body["last_seq"] == 1
    got = client.get(f"/api/runs/{run['run_id']}").json()
    assert got["run"]["input"]["location"] == "NH48 Pune"
    page = client.get(f"/api/runs/{run['run_id']}/timeline").json()
    assert [e["seq"] for e in page["events"]] == [1] and page["events"][0]["type"] == "state_change"
    assert page["next_seq"] == 1 and page["terminal"] is False
    again = client.get(f"/api/runs/{run['run_id']}/timeline?after_seq=1").json()
    assert again["events"] == [] and again["next_seq"] == 1


def test_unknown_workflow_run_and_approval_are_404_with_error_model(client: TestClient) -> None:
    r = client.post("/api/runs", json={"workflow_id": "nope_nope", "input": {}})
    assert (
        r.status_code == 404
        and r.json()["error"] == "workflow_not_found"
        and set(r.json()) == {"error", "message"}
    )
    for url in (f"/api/runs/{uuid.uuid4()}", "/api/runs/not-a-uuid", f"/api/runs/{uuid.uuid4()}/timeline"):
        g = client.get(url)
        assert g.status_code == 404 and g.json()["error"] == "run_not_found", url
    rid = client.post("/api/runs", json=VEHICLE).json()["run"]["run_id"]
    d = client.post(f"/api/runs/{rid}/approvals/{uuid.uuid4()}", json={"decision": "approve"})
    assert d.status_code == 404 and d.json()["error"] == "approval_not_found"


def test_validation_errors_never_echo_submitted_values(client: TestClient) -> None:  # A5
    canary = "SUPERSECRET-" + uuid.uuid4().hex
    bad_bodies = [
        {"input": {}},
        {"workflow_id": "vehicle_breakdown", "input": "not-an-object"},
        {"workflow_id": "vehicle_breakdown", "input": {"description": 5}},
        {"workflow_id": "vehicle_breakdown", "input": {"location": canary}},
        {"workflow_id": "vehicle_breakdown", "input": {"description": "abc"}, "extra": canary},
        {"workflow_id": "vehicle_breakdown", "input": {"description": "abc", canary: 1}},
    ]
    for body in bad_bodies:
        r = client.post("/api/runs", json=body)
        assert r.status_code == 422, body
        assert r.json()["error"] == "invalid_input" and canary not in r.text
    assert client.get("/api/runs/x/timeline?limit=0").status_code == 422
    assert client.post("/api/runs/x/approvals/y", json={"decision": "maybe"}).status_code == 422


def test_input_limits_u4(client: TestClient, engine: Engine) -> None:
    big = client.post(
        "/api/runs",
        content=b'{"workflow_id":"life_admin","input":{"task":"' + b"a" * 70_000 + b'"}}',
        headers={"content-type": "application/json"},
    )
    assert big.status_code == 413 and big.json()["error"] == "payload_too_large"
    long_text = client.post(
        "/api/runs",
        json={
            "workflow_id": "scam_investigation",
            "input": {"suspicious_content": "a" * 8000, "sender": "b" * 300},
        },
    )
    assert long_text.status_code == 201  # within both limits
    many_urls = " ".join(f"http://example.test/{i}" for i in range(11))
    r = client.post(
        "/api/runs", json={"workflow_id": "scam_investigation", "input": {"suspicious_content": many_urls}}
    )
    assert r.status_code == 422 and "URLs" in r.json()["message"]
    ten = " ".join(f"http://e.test/{i}" for i in range(10))
    assert (
        client.post(
            "/api/runs", json={"workflow_id": "scam_investigation", "input": {"suspicious_content": ten}}
        ).status_code
        == 201
    )
    with engine.connect() as c:  # rejected requests created nothing
        assert c.execute(text("SELECT count(*) FROM runs")).scalar_one() == 2


def test_cancel_before_action_and_terminal_is_409(client: TestClient) -> None:
    rid = client.post("/api/runs", json=VEHICLE).json()["run"]["run_id"]
    r = client.post(f"/api/runs/{rid}/cancel", json={"reason": "changed my mind"})
    assert r.status_code == 200 and r.json()["run"]["state"] == "cancelled"
    assert r.json()["run"]["terminal_reason"] == "changed my mind"
    ev = client.get(f"/api/runs/{rid}/timeline").json()
    assert [e["payload"].get("to") for e in ev["events"]] == ["intent", "cancelled"] and ev[
        "terminal"
    ] is True
    again = client.post(f"/api/runs/{rid}/cancel")
    assert again.status_code == 409 and again.json()["error"] == "illegal_transition"
    assert client.post(f"/api/runs/{uuid.uuid4()}/cancel").status_code == 404


def test_approval_decision_without_runtime_is_409_not_500(client: TestClient) -> None:
    rid = client.post("/api/runs", json=VEHICLE).json()["run"]["run_id"]
    r = client.post(f"/api/runs/{rid}/approvals/{uuid.uuid4()}", json={"decision": "approve"})
    assert r.status_code == 404  # no such approval; never a 5xx
