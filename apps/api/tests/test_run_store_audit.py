"""RunStore + AuditLog: persistence, concurrency, allowlist (P1), redaction canaries (K3), append-only (contract #8)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from contract.errors import ConcurrentModification, IllegalTransition, RunNotFound
from contract.models import AuditEntryInput, EventType, Evidence, RunRecord, RunState
from contract.run_state_machine import apply_transition
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.audit.sql_audit import SqlAuditLog
from app.db.run_store import SqlRunStore
from app.security.keys import make_redactor
from tests.conftest import USING_PG

pytestmark = pytest.mark.anyio


def canary(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex + uuid.uuid4().hex  # generated at runtime, never committed


def new_run(**kw: Any) -> RunRecord:
    now = datetime.now(UTC)
    base: dict[str, Any] = dict(
        run_id=str(uuid.uuid4()),
        workflow_id="wf_test",
        workflow_version="0.1.0",
        contract_version="0.1.0",
        input={"description": "x"},
        created_at=now,
        updated_at=now,
    )
    base.update(kw)
    return RunRecord(**base)


@pytest.fixture
def store(sf: sessionmaker[Session]) -> SqlRunStore:
    return SqlRunStore(sf, make_redactor())


@pytest.fixture
def audit(sf: sessionmaker[Session]) -> SqlAuditLog:
    return SqlAuditLog(sf, make_redactor())


async def test_create_get_roundtrip_and_unknown(store: SqlRunStore) -> None:
    run = await store.create_run(new_run())
    assert await store.get_run(run.run_id) == run
    assert await store.get_run(str(uuid.uuid4())) is None and await store.get_run("garbage") is None
    with pytest.raises(RunNotFound):
        await store.list_events(str(uuid.uuid4()))


async def test_save_run_optimistic_concurrency_and_state_guard(store: SqlRunStore) -> None:
    run = await store.create_run(new_run())
    nxt = apply_transition(run, RunState.EVIDENCE)
    saved = await store.save_run(nxt, expected_version=run.version)
    assert saved.state == RunState.EVIDENCE and saved.version == 1
    with pytest.raises(ConcurrentModification):
        await store.save_run(nxt, expected_version=0)
    # forged record that skips stages / leaves a terminal state is refused by the store itself
    jump = saved.model_copy(update={"state": RunState.ACTION, "version": 2})
    with pytest.raises(IllegalTransition):
        await store.save_run(jump, expected_version=1)
    done = await store.save_run(apply_transition(saved, RunState.FAILED, _ctx("boom")), expected_version=1)
    with pytest.raises(IllegalTransition):
        await store.save_run(
            done.model_copy(update={"state": RunState.PLAN, "version": 3}), expected_version=2
        )


def _ctx(reason: str):  # type: ignore[no-untyped-def]
    from contract.run_state_machine import TransitionContext

    return TransitionContext(reason=reason)


async def test_event_seq_dense_per_run(store: SqlRunStore) -> None:
    a, b = await store.create_run(new_run()), await store.create_run(new_run())
    for i in range(3):
        await store.append_event(a.run_id, RunState.INTENT, EventType.STATE_CHANGE, {"to": f"s{i}"})
    await store.append_event(b.run_id, RunState.INTENT, EventType.STATE_CHANGE, {"to": "x"})
    assert [e.seq for e in await store.list_events(a.run_id)] == [1, 2, 3]
    assert [e.seq for e in await store.list_events(b.run_id)] == [1]
    assert [e.seq for e in await store.list_events(a.run_id, after_seq=1, limit=1)] == [2]
    with pytest.raises(RunNotFound):
        await store.append_event(str(uuid.uuid4()), RunState.INTENT, EventType.ERROR, {})


async def test_timeline_payload_allowlist_p1(store: SqlRunStore) -> None:
    run = await store.create_run(new_run())
    ev = await store.append_event(
        run.run_id,
        RunState.PLAN,
        EventType.PLAN,
        {
            "summary": "s",
            "steps": [],
            "prompt": "SYSTEM PROMPT TEXT",
            "raw_output": "model said",
            "chain_of_thought": "hmm",
            "messages": [1],
        },
    )
    assert ev.payload["summary"] == "s" and ev.payload["_dropped"] == [
        "chain_of_thought",
        "messages",
        "prompt",
        "raw_output",
    ]
    assert "SYSTEM PROMPT TEXT" not in str(ev.payload) and "model said" not in str(ev.payload)
    real = await store.append_event(
        run.run_id,
        RunState.ACTION,
        EventType.ACTION,
        {
            "step_id": "step-1",
            "tool": "web_search",
            "status": "ok",
            "mocked": False,
            "output": {"results": [{"snippet": "RAW PAGE TEXT"}]},
        },
    )
    assert "RAW PAGE TEXT" not in str(real.payload) and real.payload["output"] == {
        "keys": ["results"]
    }  # raw tool response not stored
    sim = await store.append_event(
        run.run_id,
        RunState.ACTION,
        EventType.ACTION,
        {
            "step_id": "step-2",
            "tool": "dispatch_tow",
            "status": "ok",
            "mocked": True,
            "output": {"reference": "TOW-1"},
        },
    )
    assert sim.payload["output"] == {"reference": "TOW-1"}  # simulated confirmations stay visible to the UI


async def test_canary_secrets_never_reach_db_rows(
    store: SqlRunStore, audit: SqlAuditLog, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:  # K3
    env_secret = canary("env-")
    shape_secret = canary("sk-")
    red = make_redactor([env_secret])
    from app.audit.sql_audit import SqlAuditLog as A
    from app.db.session import make_sessionmaker

    sf = make_sessionmaker(engine)
    st, au = SqlRunStore(sf, red), A(sf, red)
    run = await st.create_run(
        new_run(input={"description": f"my key is {shape_secret} and {env_secret}", "api_key": env_secret})
    )
    await st.append_event(
        run.run_id,
        RunState.INTENT,
        EventType.INTENT,
        {"summary": f"use {env_secret}", "entities": {"token": shape_secret}},
    )
    await st.add_evidence(
        Evidence(
            evidence_id=str(uuid.uuid4()),
            run_id=run.run_id,
            key="k",
            kind="user_input",
            source="user",
            content={"value": shape_secret, "password": "hunter2hunter2"},
            retrieved_at=datetime.now(UTC),
            sha256="0" * 64,
        )
    )
    await au.append(
        AuditEntryInput(
            run_id=run.run_id,
            actor="system",
            event_type="x",
            payload={"note": env_secret, "authorization": f"Bearer {shape_secret}"},
        )
    )
    with engine.connect() as c:
        dump = ""
        for table in ("runs", "run_events", "evidence", "audit_log"):
            dump += str(c.execute(text(f"SELECT * FROM {table}")).fetchall())  # noqa: S608 - fixed table names
    assert env_secret not in dump and shape_secret not in dump and "hunter2hunter2" not in dump
    assert "[REDACTED" in dump


async def test_pii_masking_p2(store: SqlRunStore) -> None:
    run = await store.create_run(
        new_run(
            input={
                "description": "card 4111 1111 1111 1111 pin 4821 aadhaar 1234 5678 9012 pan ABCDE1234F call +91 98765 43210"
            }
        )
    )
    d = run.input["description"]
    for needle in ("4111 1111 1111 1111", "1234 5678 9012", "ABCDE1234F", "4821"):
        assert needle not in d, needle
    assert "98765" in d  # phone numbers are kept (investigation needs them)


async def test_audit_chain_and_listing(audit: SqlAuditLog) -> None:
    r1, r2 = str(uuid.uuid4()), str(uuid.uuid4())
    a = await audit.append(
        AuditEntryInput(run_id=r1, actor="system", event_type="run_created", payload={"n": 1})
    )
    b = await audit.append(
        AuditEntryInput(run_id=r2, actor="user:demo-user", event_type="approval_decided", payload={"n": 2})
    )
    c = await audit.append(
        AuditEntryInput(run_id=r1, actor="tool:web_search", event_type="tool_executed", payload={"n": 3})
    )
    assert (
        (a.seq, b.seq, c.seq) == (1, 2, 3)
        and a.prev_hash == ""
        and b.prev_hash == a.hash
        and c.prev_hash == b.hash
    )
    assert [r.event_type for r in await audit.list_for_run(r1)] == ["run_created", "tool_executed"]
    assert await audit.verify_chain() is True


def _disable_guard(engine: Engine) -> None:
    with engine.begin() as c:
        if engine.dialect.name == "postgresql":
            c.execute(text("ALTER TABLE audit_log DISABLE TRIGGER USER"))
        else:
            c.execute(text("DROP TRIGGER audit_log_no_update"))


async def test_tampering_is_detected_by_chain(audit: SqlAuditLog, engine: Engine) -> None:
    rid = str(uuid.uuid4())
    for i in range(3):
        await audit.append(AuditEntryInput(run_id=rid, actor="system", event_type="e", payload={"i": i}))
    assert await audit.verify_chain()
    _disable_guard(engine)  # simulate a DB admin bypassing the trigger
    with engine.begin() as c:
        c.execute(text("""UPDATE audit_log SET payload = '{"i": 99}' WHERE seq = 2"""))
    assert await audit.verify_chain() is False


async def test_audit_log_blocks_update_delete_truncate(audit: SqlAuditLog, engine: Engine) -> None:
    await audit.append(AuditEntryInput(run_id="r", actor="system", event_type="e", payload={}))
    with pytest.raises(DBAPIError), engine.begin() as c:
        c.execute(text("UPDATE audit_log SET actor = 'x'"))
    with pytest.raises(DBAPIError), engine.begin() as c:
        c.execute(text("DELETE FROM audit_log"))
    if USING_PG:
        with pytest.raises(DBAPIError), engine.begin() as c:
            c.execute(text("TRUNCATE audit_log"))
    assert len(await audit.list_for_run("r")) == 1


async def test_audit_append_has_no_mutating_api(audit: SqlAuditLog) -> None:
    public = {n for n in dir(audit) if not n.startswith("_")}
    assert public == {"append", "list_for_run", "verify_chain"}
