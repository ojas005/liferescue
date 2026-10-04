"""Vertical slice (M1): HTTP -> real SQL stores/policy/approvals/audit -> contract ReferenceRunEngine + fakes.

The engine and tools are test doubles (tests only, arch rule R3); everything the API owns is real. These tests prove the
request enters the runtime, a timeline is returned, approvals gate every simulated write, and nothing sensitive leaks.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from contract.errors import ApprovalError
from contract.fakes import MockModel
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.db.models import ApprovalRow
from app.settings import Settings
from tests.conftest import PG_URL, VEHICLE

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "injection-corpus.json").read_text())
TERMINAL = {"completed", "failed", "denied", "cancelled"}


def _container(client: TestClient) -> Any:
    return client.app.state.container  # type: ignore[attr-defined]


def tools_executed(client: TestClient) -> list[Any]:
    return list(_container(client).engine.tools_for_tests.executed)


def ports(client: TestClient) -> Any:
    return _container(client).ports


def poll_to_terminal(client: TestClient, run_id: str) -> list[dict[str, Any]]:
    """What the web client does: poll with after_seq until terminal; return every event seen, in order."""
    seen: list[dict[str, Any]] = []
    after = 0
    for _ in range(20):
        page = client.get(f"/api/runs/{run_id}/timeline", params={"after_seq": after, "limit": 5}).json()
        seen += page["events"]
        after = page["next_seq"]
        if page["terminal"]:
            return seen
    raise AssertionError("timeline never became terminal")


def new_vehicle_run(client: TestClient) -> dict[str, Any]:
    r = client.post("/api/runs", json=VEHICLE)
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def test_run_enters_runtime_and_halts_at_approval(slice_client: TestClient) -> None:
    body = new_vehicle_run(slice_client)
    run, aps = body["run"], body["approvals"]
    assert run["state"] == "approval" and run["owner"] == "demo-user"
    assert len(aps) == 2 and {a["status"] for a in aps} == {"pending"}
    assert all(a["bound_digest"] and len(a["bound_digest"]) == 64 for a in aps)
    # only READ tools have run so far; both simulated writes wait for a human
    assert {c.tool_name for c in tools_executed(slice_client)} == {"web_search"}
    page = slice_client.get(f"/api/runs/{run['run_id']}/timeline").json()
    assert [e["seq"] for e in page["events"]] == list(range(1, len(page["events"]) + 1))
    assert page["terminal"] is False and body["last_seq"] == page["next_seq"] == len(page["events"])
    types = [e["type"] for e in page["events"]]
    for t in ("intent", "evidence", "research", "plan", "policy", "approval"):
        assert t in types, t
    # P1: the real store's allowlist matched what the engine emits (nothing had to be dropped)
    assert not any("_dropped" in e["payload"] for e in page["events"])


def test_approve_both_completes_and_timeline_is_ordered_and_terminal(slice_client: TestClient) -> None:
    body = new_vehicle_run(slice_client)
    rid = body["run"]["run_id"]
    first, second = (a["approval_id"] for a in body["approvals"])
    mid = slice_client.post(
        f"/api/runs/{rid}/approvals/{first}", json={"decision": "approve", "reason": "ok"}
    )
    assert mid.status_code == 200 and mid.json()["run"]["state"] == "approval"  # one is not enough
    done = slice_client.post(f"/api/runs/{rid}/approvals/{second}", json={"decision": "approve"})
    assert done.status_code == 200
    run = done.json()["run"]
    assert run["state"] == "completed" and run["verification"]["passed"] is True
    assert [r["tool_name"] for r in run["results"]] == ["dispatch_tow", "send_message"]
    assert all(r["mocked"] for r in run["results"])  # T6 data: simulated, labelled by the contract
    assert {a["status"] for a in done.json()["approvals"]} == {"consumed"}  # single use
    events = poll_to_terminal(slice_client, rid)
    assert [e["seq"] for e in events] == list(
        range(1, len(events) + 1)
    )  # dense, in order, no duplicates across pages
    states = [e["payload"]["to"] for e in events if e["type"] == "state_change"]
    assert (
        states[0] == "intent"
        and states[-1] == "completed"
        and "action" in states
        and "verification" in states
    )
    assert states.index("approval") < states.index("action")  # nothing executed before approval
    assert not any("_dropped" in e["payload"] for e in events)


def test_deny_ends_denied_and_no_write_runs(slice_client: TestClient) -> None:
    body = new_vehicle_run(slice_client)
    rid, ap = body["run"]["run_id"], body["approvals"][0]["approval_id"]
    r = slice_client.post(f"/api/runs/{rid}/approvals/{ap}", json={"decision": "deny", "reason": "no thanks"})
    assert r.status_code == 200 and r.json()["run"]["state"] == "denied"
    assert {c.tool_name for c in tools_executed(slice_client)} == {"web_search"}
    assert poll_to_terminal(slice_client, rid)  # terminal immediately, no hang


def test_cancel_at_approval_stops_everything(slice_client: TestClient) -> None:
    body = new_vehicle_run(slice_client)
    rid = body["run"]["run_id"]
    r = slice_client.post(f"/api/runs/{rid}/cancel", json={"reason": "never mind"})
    assert r.status_code == 200 and r.json()["run"]["state"] == "cancelled"
    assert {a["status"] for a in r.json()["approvals"]} <= {"revoked", "denied"}
    assert {c.tool_name for c in tools_executed(slice_client)} == {"web_search"}
    # a revoked approval can no longer authorise anything
    late = slice_client.post(
        f"/api/runs/{rid}/approvals/{body['approvals'][0]['approval_id']}", json={"decision": "approve"}
    )
    assert late.status_code == 409 and late.json()["error"] in {"approval_invalid", "illegal_transition"}
    assert {c.tool_name for c in tools_executed(slice_client)} == {"web_search"}


def test_t5_same_decision_is_idempotent_flip_is_409(slice_client: TestClient) -> None:
    body = new_vehicle_run(slice_client)
    rid, ap = body["run"]["run_id"], body["approvals"][0]["approval_id"]
    url = f"/api/runs/{rid}/approvals/{ap}"
    a = slice_client.post(url, json={"decision": "approve"}, headers={"X-Actor-Id": "alice"})
    n_events = len(slice_client.get(f"/api/runs/{rid}/timeline").json()["events"])
    b = slice_client.post(url, json={"decision": "approve"}, headers={"X-Actor-Id": "mallory"})
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    first = next(x for x in b.json()["approvals"] if x["approval_id"] == ap)
    assert first["decided_by"] == "alice"  # first decision stands
    assert (
        len(slice_client.get(f"/api/runs/{rid}/timeline").json()["events"]) == n_events
    )  # replay adds nothing
    flip = slice_client.post(url, json={"decision": "deny"})
    assert flip.status_code == 409 and flip.json()["error"] == "approval_invalid"
    assert set(flip.json()) == {"error", "message"}


def test_t5_foreign_approval_is_404(slice_client: TestClient) -> None:
    a, b = new_vehicle_run(slice_client), new_vehicle_run(slice_client)
    foreign = a["approvals"][0]["approval_id"]
    r = slice_client.post(f"/api/runs/{b['run']['run_id']}/approvals/{foreign}", json={"decision": "approve"})
    assert r.status_code == 404 and r.json()["error"] == "approval_not_found"
    still = slice_client.get(f"/api/runs/{a['run']['run_id']}").json()
    assert {x["status"] for x in still["approvals"]} == {"pending"}


def test_t4_args_changed_after_approval_cannot_execute(slice_client: TestClient) -> None:
    """The digest is bound at approval creation; consuming with different args fails and does not burn the approval."""
    body = new_vehicle_run(slice_client)
    rid, ap = body["run"]["run_id"], body["approvals"][0]
    slice_client.post(f"/api/runs/{rid}/approvals/{ap['approval_id']}", json={"decision": "approve"})
    svc = ports(slice_client).approvals
    with pytest.raises(ApprovalError):
        asyncio.run(svc.consume(ap["approval_id"], "0" * 64))
    got = asyncio.run(svc.get(ap["approval_id"]))
    assert got.status.value == "approved"  # still approved, not consumed by the failed attempt


def test_expired_approval_cannot_be_approved(
    make_slice_client: Callable[..., TestClient], sf: sessionmaker[Any]
) -> None:
    client = make_slice_client()
    body = new_vehicle_run(client)
    rid, ap = body["run"]["run_id"], body["approvals"][0]["approval_id"]
    with sf.begin() as s:  # age the approval past its 900 s TTL
        row = s.get(ApprovalRow, uuid.UUID(ap))
        assert row is not None
        row.expires_at = datetime(2000, 1, 1, tzinfo=UTC)
    r = client.post(f"/api/runs/{rid}/approvals/{ap}", json={"decision": "approve"})
    assert r.status_code == 409 and r.json()["error"] == "approval_invalid"
    assert {c.tool_name for c in tools_executed(client)} == {"web_search"}


def test_audit_chain_verifies_after_full_run_and_has_no_mutation_path(slice_client: TestClient) -> None:
    body = new_vehicle_run(slice_client)
    rid = body["run"]["run_id"]
    for a in body["approvals"]:
        slice_client.post(f"/api/runs/{rid}/approvals/{a['approval_id']}", json={"decision": "approve"})
    audit = ports(slice_client).audit
    assert asyncio.run(audit.verify_chain()) is True
    kinds = [e.event_type for e in asyncio.run(audit.list_for_run(rid))]
    assert kinds[0] == "run_created" and "approval_decided" in kinds and "tool_executed" in kinds
    assert not [m for m in dir(audit) if m.lstrip("_").startswith(("update", "delete", "remove", "truncate"))]


def test_k3_canary_never_appears_in_stdout_stderr_db_or_responses(
    make_slice_client: Callable[..., TestClient],
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "CANARY-" + uuid.uuid4().hex + "-nebius"
    monkeypatch.setenv("NEBIUS_API_KEY", canary)
    shaped = "sk-" + uuid.uuid4().hex + uuid.uuid4().hex[:8]  # a key-shaped value pasted by a careless user
    settings = Settings(
        _env_file=None, liferescue_env="test", model_adapter="mock", database_url=PG_URL or "sqlite://"
    )
    client = make_slice_client(settings_override=settings)
    payload = {
        "workflow_id": "vehicle_breakdown",
        "input": {"description": f"stuck. my key is {shaped} and Bearer {canary}", "location": "Pune"},
    }
    r = client.post("/api/runs", json=payload)
    assert r.status_code == 201
    body = r.json()
    rid = body["run"]["run_id"]
    responses = [r.text, client.get("/api/health").text, client.get(f"/api/runs/{rid}/timeline").text]
    for a in body["approvals"]:
        responses.append(
            client.post(f"/api/runs/{rid}/approvals/{a['approval_id']}", json={"decision": "approve"}).text
        )
    responses.append(
        client.post("/api/runs", json={"workflow_id": "x", "input": {"k": canary}}).text
    )  # error path
    responses.append(client.post("/api/runs", content=b"{" + canary.encode()).text)  # malformed body
    dump = ""
    with engine.connect() as c:
        for table in ("runs", "run_events", "approvals", "evidence", "audit_log"):
            dump += str(c.execute(text(f"SELECT * FROM {table}")).fetchall())  # noqa: S608 - fixed names
    out = capfd.readouterr()
    haystacks = {
        "responses": "\n".join(responses),
        "db": dump,
        "stdout": out.out,
        "stderr": out.err,
        "logs": caplog.text,
    }
    for where, hay in haystacks.items():
        assert canary not in hay, f"env canary leaked into {where}"
        assert shaped not in hay, f"key-shaped secret leaked into {where}"
    assert "[REDACTED" in haystacks["db"]  # redaction ran at write time, not just on read


@pytest.mark.parametrize("case", CORPUS["texts"], ids=[t["id"] for t in CORPUS["texts"]])
@pytest.mark.parametrize(
    ("workflow_id", "field"),
    [("scam_investigation", "suspicious_content"), ("vehicle_breakdown", "description")],
)
def test_injection_corpus_never_executes_a_write_without_approval(
    make_slice_client: Callable[..., TestClient], case: dict[str, str], workflow_id: str, field: str
) -> None:
    """Provisional (LR 08 corpus, invariants I1/I2/I5 at the API+persistence+policy level).

    The model here is a deterministic double, so this does NOT prove the real model resists injection (that is LR 06's
    gateway/prompt test). It proves: hostile text as input cannot make the API/policy/approval stack run a simulated
    write, create or decide an approval, or leak a canary; the run halts for a human or ends in a terminal state."""
    client = make_slice_client(MockModel())
    text_in = case["text"] if len(case["text"]) <= 8000 else case["text"][:8000]
    r = client.post("/api/runs", json={"workflow_id": workflow_id, "input": {field: text_in}})
    assert r.status_code in (201, 422), r.text
    if r.status_code == 422:
        return  # rejected by input schema: fail closed
    body = r.json()
    assert body["run"]["state"] in ({"approval"} | TERMINAL)
    assert all(a["status"] == "pending" for a in body["approvals"])  # nothing was approved by the text (I2)
    executed = tools_executed(client)
    assert {c.tool_name for c in executed} <= {"web_search"}  # I1/I2: no write tool ran without approval
    assert body["run"]["results"] == []
    assert not [a for a in body["approvals"] if a["status"] != "pending"]
