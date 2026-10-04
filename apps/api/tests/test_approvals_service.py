"""SqlApprovalService: digest binding, single use, expiry, replay, concurrency (T4, T5)."""

import asyncio
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from contract.errors import ApprovalError
from contract.models import (
    ActionRequest,
    ApprovalStatus,
    PolicyDecision,
    PolicyOutcome,
    RiskLevel,
    RunRecord,
)
from sqlalchemy.orm import Session, sessionmaker

from app.approvals.sql_service import SqlApprovalService
from app.db.run_store import SqlRunStore
from app.security.keys import make_redactor
from tests.conftest import USING_PG

pytestmark = pytest.mark.anyio


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def make_run(sf: sessionmaker[Session]) -> str:
    rid = str(uuid.uuid4())
    now = datetime.now(UTC)
    await SqlRunStore(sf, make_redactor()).create_run(
        RunRecord(
            run_id=rid,
            workflow_id="wf_test",
            workflow_version="0.1.0",
            contract_version="0.1.0",
            input={},
            created_at=now,
            updated_at=now,
        )
    )
    return rid


def action(run_id: str, **params: object) -> ActionRequest:
    return ActionRequest(
        run_id=run_id,
        workflow_id="wf_test",
        workflow_version="0.1.0",
        step_id="step-1",
        tool_name="dispatch_tow",
        params=params or {"to": "Pune"},
        policy_version="pv",
        requested_by="demo-user",
    )


def decision(req: ActionRequest, outcome: PolicyOutcome = PolicyOutcome.NEEDS_APPROVAL) -> PolicyDecision:
    return PolicyDecision(
        step_id=req.step_id,
        outcome=outcome,
        risk=RiskLevel.HIGH,
        rule_id="tow",
        reason="r",
        policy_version="pv",
        action_digest=req.digest(),
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def svc(sf: sessionmaker[Session], clock: Clock) -> SqlApprovalService:
    return SqlApprovalService(sf, make_redactor(), clock)


async def test_create_binds_digest_and_ttl(
    svc: SqlApprovalService, sf: sessionmaker[Session], clock: Clock
) -> None:
    req = action(await make_run(sf))
    ap = await svc.create(req, decision(req), "Dispatch tow", 900)
    assert ap.status == ApprovalStatus.PENDING and ap.bound_digest == req.digest()
    assert ap.expires_at == clock.now + timedelta(seconds=900) and ap.policy_version == "pv"


async def test_create_rejects_non_gated_or_mismatched_decisions(
    svc: SqlApprovalService, sf: sessionmaker[Session]
) -> None:
    req = action(await make_run(sf))
    with pytest.raises(ApprovalError):
        await svc.create(req, decision(req, PolicyOutcome.ALLOW), "x", 900)
    with pytest.raises(ApprovalError):
        await svc.create(
            req, decision(action(req.run_id, to="elsewhere")), "x", 900
        )  # decision for a different action
    with pytest.raises(ApprovalError):
        await svc.create(req, decision(req), "x", 0)


async def test_decide_only_from_pending_and_records_decider(
    svc: SqlApprovalService, sf: sessionmaker[Session]
) -> None:
    req = action(await make_run(sf))
    ap = await svc.create(req, decision(req), "s", 900)
    done = await svc.decide(ap.approval_id, True, "demo-user", "ok")
    assert (
        done.status == ApprovalStatus.APPROVED
        and done.decided_by == "demo-user"
        and done.decided_at
        and done.reason == "ok"
    )
    for approve in (True, False):  # replay / flip after the first decision
        with pytest.raises(ApprovalError):
            await svc.decide(ap.approval_id, approve, "attacker")
    assert (await svc.get(ap.approval_id)).decided_by == "demo-user"  # type: ignore[union-attr]


async def test_deny_is_terminal(svc: SqlApprovalService, sf: sessionmaker[Session]) -> None:
    req = action(await make_run(sf))
    ap = await svc.create(req, decision(req), "s", 900)
    assert (await svc.decide(ap.approval_id, False, "demo-user")).status == ApprovalStatus.DENIED
    with pytest.raises(ApprovalError):
        await svc.consume(ap.approval_id, req.digest())


async def test_consume_is_digest_bound_and_single_use(
    svc: SqlApprovalService, sf: sessionmaker[Session]
) -> None:
    req = action(await make_run(sf))
    ap = await svc.create(req, decision(req), "s", 900)
    with pytest.raises(ApprovalError, match="not approved"):
        await svc.consume(ap.approval_id, req.digest())  # pending
    await svc.decide(ap.approval_id, True, "demo-user")
    tampered = action(req.run_id, to="Mumbai").digest()  # args changed after approval
    with pytest.raises(ApprovalError, match="different action digest"):
        await svc.consume(ap.approval_id, tampered)
    assert (await svc.get(ap.approval_id)).status == ApprovalStatus.APPROVED  # type: ignore[union-attr]  # failed attempt did not burn it
    assert (await svc.consume(ap.approval_id, req.digest())).status == ApprovalStatus.CONSUMED
    with pytest.raises(ApprovalError, match="consumed"):
        await svc.consume(ap.approval_id, req.digest())  # replay


async def test_expiry(svc: SqlApprovalService, sf: sessionmaker[Session], clock: Clock) -> None:
    req = action(await make_run(sf))
    ap = await svc.create(req, decision(req), "s", 60)
    clock.now += timedelta(seconds=61)
    with pytest.raises(ApprovalError):
        await svc.decide(ap.approval_id, True, "demo-user")
    assert (await svc.get(ap.approval_id)).status == ApprovalStatus.EXPIRED  # type: ignore[union-attr]
    ap2 = await svc.create(req, decision(req), "s", 60)
    await svc.decide(ap2.approval_id, True, "demo-user")
    clock.now += timedelta(seconds=61)
    with pytest.raises(ApprovalError, match="expired"):
        await svc.consume(ap2.approval_id, req.digest())  # approved but unused approvals expire too


async def test_revoke_pending_and_unknown_ids(svc: SqlApprovalService, sf: sessionmaker[Session]) -> None:
    run_id = await make_run(sf)
    req = action(run_id)
    a1 = await svc.create(req, decision(req), "s", 900)
    a2 = await svc.create(req, decision(req), "s", 900)
    await svc.decide(a2.approval_id, True, "demo-user")
    revoked = await svc.revoke_pending(run_id)
    assert {a.status for a in revoked} == {ApprovalStatus.REVOKED} and len(revoked) == 2
    with pytest.raises(ApprovalError):
        await svc.consume(a2.approval_id, req.digest())
    assert (await svc.get(a1.approval_id)).status == ApprovalStatus.REVOKED  # type: ignore[union-attr]
    assert await svc.get("not-a-uuid") is None and await svc.list_for_run("nope") == []
    with pytest.raises(ApprovalError):
        await svc.decide(str(uuid.uuid4()), True, "demo-user")


async def test_summary_and_reason_are_redacted(svc: SqlApprovalService, sf: sessionmaker[Session]) -> None:
    canary = "sk-" + uuid.uuid4().hex + uuid.uuid4().hex
    req = action(await make_run(sf))
    ap = await svc.create(req, decision(req), f"Dispatch using key {canary}", 900)
    done = await svc.decide(ap.approval_id, True, "demo-user", f"because {canary}")
    assert canary not in ap.summary and canary not in (done.reason or "")


@pytest.mark.skipif(not USING_PG, reason="needs real PostgreSQL row-level atomicity")
def test_concurrent_consume_has_exactly_one_winner(sf: sessionmaker[Session]) -> None:
    svc = SqlApprovalService(sf, make_redactor())
    req = action(asyncio.run(make_run(sf)))
    ap = asyncio.run(svc.create(req, decision(req), "s", 900))
    asyncio.run(svc.decide(ap.approval_id, True, "demo-user"))
    results: list[str] = []

    def worker() -> None:
        try:
            asyncio.run(svc.consume(ap.approval_id, req.digest()))
            results.append("ok")
        except ApprovalError:
            results.append("denied")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1 and results.count("denied") == 7
