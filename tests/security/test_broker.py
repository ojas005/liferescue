"""KAN-45 step 3 tests: broker lifecycle, access control, fail-closed (T-01, T-03..T-14, T-28, T-29)."""

import ast
import threading
import unittest
from datetime import timedelta
from pathlib import Path

from fixtures_broker import DB_REF, DEFAULT_POLICY, MODEL_REF, SEARCH_REF, Rig

from packages.secrets.audit import AuditEventType as E
from packages.secrets.audit import InMemoryAuditSink
from packages.secrets.broker import CredentialBroker
from packages.secrets.codes import DenialReason as D
from packages.secrets.codes import RequestReason, RevokeReason
from packages.secrets.config import BrokerConfig
from packages.secrets.errors import ConfigurationError, Denied, PolicyError
from packages.secrets.memory_backend import InMemoryBackend
from packages.secrets.policy import Grant, Policy, policy_from_mapping
from packages.secrets.secret_types import (
    CredentialRequest,
    Environment,
    GatewayIdentity,
    LeaseHandle,
    LeaseState,
    Purpose,
    ScopedSecret,
    SecretRef,
    SecretValue,
)
from packages.secrets.tasks import InMemoryTaskRegistry, TaskState
from packages.secrets.testing import make_canary


class IssueAndNoLeak(unittest.TestCase):
    def test_T01_lease_for_each_purpose_has_no_value_and_is_audited(self):
        rig = Rig(tasks=(("T-1", "R-1", "LR-06"), ("T-2", "R-2", "LR-04")))
        cases = [
            (MODEL_REF, "T-1", "R-1", "LR-06"),
            (SEARCH_REF, "T-1", "R-1", "LR-06"),
            (DB_REF, "T-2", "R-2", "LR-04"),
        ]
        for ref, task, run, agent in cases:
            with self.subTest(purpose=ref.purpose):
                handle = rig.request(ref, task=task, run=run, agent=agent)
                self.assertIsInstance(handle, LeaseHandle)
                canary = rig.canaries[ref]
                for text in (
                    repr(handle),
                    str(handle),
                    repr(handle.__dict__),
                    repr(handle.ref),
                ):
                    self.assertNotIn(canary, text)
                self.assertGreaterEqual(len(handle.lease_id), 22)  # 128 bit urlsafe
                issued = [
                    e
                    for e in rig.events(E.LEASE_ISSUED)
                    if e.lease_id == handle.lease_id
                ]
                self.assertEqual(len(issued), 1)
        self.assertNotIn(next(iter(rig.canaries.values())), rig.all_audit_text())

    def test_lease_ids_are_unique_and_random(self):
        rig = Rig(
            config=BrokerConfig(max_leases_per_task=4),
            tasks=tuple((f"T-{i}", "R-1", "LR-06") for i in range(20)),
        )
        ids = {rig.request(task=f"T-{i}").lease_id for i in range(20)}
        self.assertEqual(len(ids), 20)

    def test_use_yields_value_only_inside_scope_and_wipes_after(self):
        rig = Rig()
        h = rig.request()
        scoped = rig.use(h)
        self.assertIsInstance(scoped, ScopedSecret)
        self.assertNotIn(rig.canaries[MODEL_REF], repr(scoped))
        with scoped as value:
            self.assertIsInstance(value, SecretValue)
            self.assertNotIn(rig.canaries[MODEL_REF], f"{value}")
            with value.reveal() as raw:
                self.assertEqual(raw, rig.canaries[MODEL_REF])
        self.assertTrue(value.wiped)
        with rig.use(h) as again:  # lease's own copy was not wiped  # noqa: SIM117 - nested contexts kept for readability of the security test
            with again.reveal() as raw:
                self.assertEqual(raw, rig.canaries[MODEL_REF])

    def test_handle_for_agents_never_holds_secret_value(self):
        rig = Rig()
        h = rig.request()
        for v in vars(h).values():
            self.assertNotIsInstance(v, SecretValue)


class AccessDenial(unittest.TestCase):
    def assertDenied(self, rig, reason, fn, *args, **kw):
        with self.assertRaises(Denied) as ctx:
            fn(*args, **kw)
        self.assertIs(ctx.exception.reason, reason)
        self.assertIsNone(ctx.exception.__cause__)
        self.assertIsNone(ctx.exception.__context__)
        return ctx.exception

    def test_T03_unauthorised_agent_denied_audited_no_handle(self):
        rig = Rig(tasks=(("T-1", "R-1", "LR-06"), ("T-9", "R-9", "LR-05")))
        self.assertDenied(
            rig,
            D.NO_GRANT,
            rig.request,
            MODEL_REF,
            task="T-9",
            run="R-9",
            agent="LR-05",
        )
        self.assertDenied(
            rig, D.NO_GRANT, rig.request, DB_REF, task="T-1", run="R-1", agent="LR-06"
        )  # wrong purpose
        denied = rig.events(E.LEASE_DENIED)
        self.assertEqual([e.reason_code for e in denied], ["no_grant", "no_grant"])
        self.assertEqual(rig.broker.live_lease_count(), 0)
        self.assertEqual(rig.broker.leased_values.__len__(), 0)
        self.assertEqual(
            rig.backend.resolve_count,
            0,
            "backend must not even be consulted for a denied request",
        )

    def test_T04_unknown_purpose_ref_environment_fail_closed(self):
        rig = Rig()
        base = {
            "task_id": "T-1",
            "run_id": "R-1",
            "agent_id": "LR-06",
            "reason_code": "model_call",
        }
        for label, ref in [
            ("unknown purpose", "secretref://mock/not_a_purpose/mock-model-key"),
            (
                "unknown environment",
                "secretref://staging/model_inference/mock-model-key",
            ),
            ("garbage", "not a ref"),
            ("bad name", "secretref://mock/model_inference/UP PER"),
        ]:
            with self.subTest(label):
                self.assertDenied(
                    rig,
                    D.MALFORMED_REQUEST,
                    rig.broker.request_wire,
                    dict(base, ref=ref),
                )
        # unknown name: not in the policy
        self.assertDenied(
            rig,
            D.NO_GRANT,
            rig.broker.request_wire,
            dict(base, ref="secretref://mock/model_inference/mock-unlisted"),
        )
        # in policy but the backend has no value
        rig.backend._values.pop(MODEL_REF)
        self.assertDenied(
            rig,
            D.UNKNOWN_REF,
            rig.broker.request_wire,
            dict(base, ref=MODEL_REF.to_string()),
        )
        # environment not served
        self.assertDenied(
            rig,
            D.ENV_NOT_SERVED,
            rig.broker.request_wire,
            dict(base, ref="secretref://test/model_inference/mock-model-key"),
        )
        self.assertEqual(rig.broker.live_lease_count(), 0)
        # malformed denials are audited and carry no hostile content
        hostile = make_canary("x ", 24)
        self.assertDenied(
            rig,
            D.MALFORMED_REQUEST,
            rig.broker.request_wire,
            {"task_id": hostile, "agent_id": hostile, "ref": hostile, "reason_code": 5},
        )
        self.assertDenied(
            rig, D.MALFORMED_REQUEST, rig.broker.request_wire, "not a mapping"
        )
        self.assertNotIn(hostile, rig.all_audit_text())

    def test_wire_request_valid(self):
        rig = Rig()
        h = rig.broker.request_wire(
            {
                "task_id": "T-1",
                "run_id": "R-1",
                "agent_id": "LR-06",
                "ref": MODEL_REF.to_string(),
                "reason_code": "model_call",
                "requested_ttl_seconds": 60,
            }
        )
        self.assertEqual(h.ref, MODEL_REF)
        for bad_ttl in (True, "60", float("nan"), float("inf")):
            with self.assertRaises(Denied):
                rig.broker.request_wire(
                    {
                        "task_id": "T-1",
                        "run_id": "R-1",
                        "agent_id": "LR-06",
                        "ref": SEARCH_REF.to_string(),
                        "reason_code": "model_call",
                        "requested_ttl_seconds": bad_ttl,
                    }
                )

    def test_T05_ttl_above_maximum_is_denied_not_clamped(self):
        rig = Rig()
        self.assertDenied(
            rig, D.TTL_EXCEEDS_MAX, rig.request, MODEL_REF, ttl=timedelta(minutes=16)
        )  # grant max is 900 s
        self.assertDenied(
            rig, D.TTL_EXCEEDS_MAX, rig.request, SEARCH_REF, ttl=timedelta(minutes=31)
        )  # global max 30 min
        self.assertDenied(rig, D.TTL_INVALID, rig.request, SEARCH_REF, ttl=timedelta(0))
        self.assertDenied(
            rig, D.TTL_INVALID, rig.request, SEARCH_REF, ttl=timedelta(seconds=-1)
        )
        h = rig.request(
            SEARCH_REF, ttl=timedelta(minutes=30)
        )  # exactly the maximum is fine
        self.assertEqual(h.expires_at - rig.clock.wall(), timedelta(minutes=30))

    def test_default_ttl_comes_from_config(self):
        rig = Rig(
            config=BrokerConfig(
                default_ttl=timedelta(seconds=90), max_ttl=timedelta(minutes=5)
            )
        )
        h = rig.request()
        self.assertEqual(h.expires_at - rig.clock.wall(), timedelta(seconds=90))
        rig.clock.advance(89)
        rig.use(h)
        rig.clock.advance(1)
        self.assertDenied(rig, D.LEASE_EXPIRED, rig.use, h)

    def test_T14_production_always_refused_for_any_agent(self):
        rig = Rig()
        prod = SecretRef.parse("secretref://production/model_inference/mock-model-key")
        for agent in ("LR-06", "LR-01", "LR-08", "LR-04"):
            with self.subTest(agent=agent):
                rig.registry.register("T-P", "R-P", agent)
                self.assertDenied(
                    rig,
                    D.PRODUCTION_REFUSED,
                    rig.request,
                    prod,
                    task="T-P",
                    run="R-P",
                    agent=agent,
                )
        self.assertTrue(all(e.alert for e in rig.events(E.LEASE_DENIED)))
        self.assertEqual(len(rig.alerts), 4)
        self.assertEqual(rig.backend.resolve_count, 0)

    def test_T14_production_refused_even_if_policy_and_config_are_tampered(self):
        prod = SecretRef(
            Environment.PRODUCTION, Purpose.MODEL_INFERENCE, "mock-model-key"
        )
        tampered_policy = Policy(
            grants=(
                Grant(
                    "LR-06",
                    Purpose.MODEL_INFERENCE,
                    frozenset({"mock-model-key"}),
                    frozenset({Environment.PRODUCTION}),
                ),
            )
        )
        rig = Rig()
        cfg = BrokerConfig()
        object.__setattr__(
            cfg,
            "served_environments",
            frozenset({Environment.MOCK, Environment.PRODUCTION}),
        )  # bypass validation
        # Startup refuses a tampered config outright ...
        with self.assertRaises(ConfigurationError):
            CredentialBroker(
                backend=rig.backend,
                policy=tampered_policy,
                task_registry=rig.registry,
                config=cfg,
            )
        # ... and if the config is tampered AFTER startup, the constant check still refuses.
        broker = CredentialBroker(
            backend=rig.backend,
            policy=tampered_policy,
            task_registry=rig.registry,
            config=BrokerConfig(),
            clock=rig.clock,
            audit_sink=InMemoryAuditSink(),
        )
        object.__setattr__(
            broker._config,
            "served_environments",
            frozenset({Environment.MOCK, Environment.PRODUCTION}),
        )
        req = CredentialRequest("T-1", "R-1", "LR-06", prod, RequestReason.MODEL_CALL)
        with self.assertRaises(Denied) as ctx:
            broker.request(req)
        self.assertIs(ctx.exception.reason, D.PRODUCTION_REFUSED)

    def test_T14_startup_fails_if_backend_declares_production_or_unserved_env(self):
        class ProdBackend(InMemoryBackend):
            environment = Environment.PRODUCTION

        class TestEnvBackend(InMemoryBackend):
            environment = Environment.TEST

        class NoEnvBackend:
            def health(self):
                return True

        registry = InMemoryTaskRegistry()
        for backend in (ProdBackend(), TestEnvBackend(), NoEnvBackend()):
            with self.subTest(backend=type(backend).__name__):  # noqa: SIM117 - nested contexts kept for readability of the security test
                with self.assertRaises(ConfigurationError):
                    CredentialBroker(
                        backend=backend,
                        policy=policy_from_mapping(DEFAULT_POLICY),
                        task_registry=registry,
                    )
        with self.assertRaises(ConfigurationError):
            CredentialBroker(
                backend=InMemoryBackend(),
                policy=policy_from_mapping(DEFAULT_POLICY),
                task_registry=None,
            )  # type: ignore[arg-type]
        with self.assertRaises(PolicyError):
            policy_from_mapping(
                {
                    "version": 1,
                    "grants": [
                        dict(DEFAULT_POLICY["grants"][0], environments=["production"])
                    ],
                }
            )

    def test_task_must_be_live_and_ids_must_match(self):
        rig = Rig()
        self.assertDenied(
            rig, D.TASK_NOT_LIVE, rig.request, MODEL_REF, task="T-unknown"
        )
        self.assertDenied(
            rig, D.TASK_NOT_LIVE, rig.request, MODEL_REF, run="R-other"
        )  # run mismatch
        rig.registry.register("T-5", "R-5", "LR-04")
        self.assertDenied(
            rig,
            D.TASK_NOT_LIVE,
            rig.request,
            MODEL_REF,
            task="T-5",
            run="R-5",
            agent="LR-06",
        )  # agent mismatch
        rig.registry.unavailable = True
        self.assertDenied(rig, D.TASK_REGISTRY_UNAVAILABLE, rig.request, MODEL_REF)
        self.assertTrue(rig.events(E.LEASE_DENIED)[-1].alert)

    def test_denial_exceptions_carry_codes_only(self):
        rig = Rig()
        hostile = make_canary("T-", 20)
        try:
            rig.request(MODEL_REF, task=hostile)
        except Denied as exc:
            self.assertEqual(str(exc), "denied: task_not_live")
            self.assertNotIn(hostile, repr(exc))


class LeaseLifecycle(unittest.TestCase):
    def assertDenied(self, reason, fn, *args, **kw):
        with self.assertRaises(Denied) as ctx:
            fn(*args, **kw)
        self.assertIs(ctx.exception.reason, reason)

    def test_T06_use_after_expiry_fails_state_expired_audited_once(self):
        rig = Rig()
        h = rig.request(ttl=timedelta(minutes=5))
        rig.use(h)
        self.assertEqual(len(rig.broker.leased_values), 1)
        rig.minutes(5)
        self.assertDenied(D.LEASE_EXPIRED, rig.use, h)
        self.assertIs(rig.broker.lease_state(h.lease_id), LeaseState.EXPIRED)
        self.assertDenied(D.LEASE_EXPIRED, rig.use, h)  # second attempt
        self.assertEqual(
            len(rig.events(E.LEASE_EXPIRED)), 1, "exactly one expiry event per lease"
        )
        self.assertEqual(len(rig.broker.leased_values), 0, "value dropped on expiry")
        self.assertIn((MODEL_REF, h.lease_id), rig.backend.revoked)

    def test_sweep_drops_expired_leases_without_any_use(self):
        rig = Rig(config=BrokerConfig(sweep_interval=timedelta(seconds=30)))
        rig.request(ttl=timedelta(minutes=1))
        rig.clock.advance(61)
        self.assertEqual(rig.broker.maybe_sweep(), 1)
        self.assertEqual(len(rig.broker.leased_values), 0)
        self.assertEqual(len(rig.events(E.LEASE_EXPIRED)), 1)
        self.assertEqual(rig.broker.maybe_sweep(), 0)  # interval not elapsed again
        self.assertEqual(len(rig.events(E.LEASE_EXPIRED)), 1)

    def test_maybe_sweep_respects_interval(self):
        rig = Rig(config=BrokerConfig(sweep_interval=timedelta(seconds=30)))
        rig.broker.maybe_sweep()
        rig.request(ttl=timedelta(seconds=5))
        rig.clock.advance(10)
        self.assertEqual(
            rig.broker.maybe_sweep(),
            0,
            "30 s interval not yet elapsed since the last sweep",
        )
        rig.clock.advance(25)
        self.assertEqual(rig.broker.maybe_sweep(), 1)

    def test_T07_task_end_failure_cancel_stop_revoke_before_finish(self):
        for outcome, reason in [
            (TaskState.COMPLETED, "task_end"),
            (TaskState.FAILED, "task_failed"),
            (TaskState.CANCELLED, "task_cancelled"),
            (TaskState.STOPPED, "stop"),
        ]:
            with self.subTest(outcome=outcome):
                rig = Rig()
                h1, h2 = rig.request(MODEL_REF), rig.request(SEARCH_REF)
                seen = {}
                original = rig.broker.revoke_task

                def spy(task_id, *, reason_code, _orig=original, _rig=rig):
                    seen["state_during_revoke"] = _rig.registry.state(task_id)  # noqa: B023 - closure invoked within the same iteration
                    return _orig(task_id, reason_code=reason_code)

                rig.broker.revoke_task = spy
                self.assertEqual(
                    rig.registry.end_task("T-1", outcome, broker=rig.broker), 2
                )
                self.assertIsNot(
                    seen["state_during_revoke"],
                    outcome,
                    "must not be marked finished yet",
                )
                self.assertIs(rig.registry.state("T-1"), outcome)
                self.assertEqual(rig.broker.live_lease_count("T-1"), 0)
                self.assertEqual(len(rig.broker.leased_values), 0)
                self.assertDenied(D.LEASE_REVOKED, rig.use, h1)
                self.assertDenied(D.LEASE_REVOKED, rig.use, h2)
                self.assertEqual(
                    [e.reason_code for e in rig.events(E.LEASE_REVOKED)],
                    [reason, reason],
                )
                self.assertEqual(len(rig.events(E.LEASE_REVOKED)), 2)

    def test_end_task_refuses_to_finish_if_a_lease_stays_live(self):
        rig = Rig()
        rig.request()
        rig.broker.revoke_task = lambda task_id, *, reason_code: (
            0
        )  # simulate a broken revoke
        with self.assertRaises(RuntimeError):
            rig.registry.end_task("T-1", TaskState.COMPLETED, broker=rig.broker)
        self.assertIsNot(rig.registry.state("T-1"), TaskState.COMPLETED)

    def test_use_after_task_not_live_denies_and_revokes_defensively(self):
        rig = Rig()
        h = rig.request()
        rig.registry._tasks["T-1"][2] = (
            TaskState.CANCELLED
        )  # orchestrator forgot to revoke
        self.assertDenied(D.TASK_NOT_LIVE, rig.use, h)
        self.assertIs(rig.broker.lease_state(h.lease_id), LeaseState.REVOKED)
        self.assertEqual(len(rig.broker.leased_values), 0)

    def test_revoke_all_global_stop(self):
        rig = Rig(tasks=(("T-1", "R-1", "LR-06"), ("T-2", "R-2", "LR-06")))
        rig.request(task="T-1", run="R-1")
        rig.request(task="T-2", run="R-2")
        self.assertEqual(rig.broker.revoke_all(reason_code=RevokeReason.STOP), 2)
        self.assertEqual(rig.broker.live_lease_count(), 0)
        self.assertEqual(rig.broker.revoke_all(reason_code=RevokeReason.STOP), 0)

    def test_revoke_is_idempotent_one_event(self):
        rig = Rig()
        h = rig.request()
        self.assertTrue(
            rig.broker.revoke(h.lease_id, reason_code=RevokeReason.OWNER_ACTION)
        )
        self.assertFalse(
            rig.broker.revoke(h.lease_id, reason_code=RevokeReason.OWNER_ACTION)
        )
        self.assertFalse(
            rig.broker.revoke("no-such-lease", reason_code=RevokeReason.OWNER_ACTION)
        )
        self.assertEqual(len(rig.events(E.LEASE_REVOKED)), 1)
        with self.assertRaises(Exception):  # noqa: B017 - test asserts any rejection
            rig.broker.revoke(h.lease_id, reason_code="owner_action")  # type: ignore[arg-type]

    def test_T10_T11_no_renewal_duplicate_denied_reissue_after_expiry_reevaluates_policy(
        self,
    ):
        rig = Rig()
        self.assertFalse(
            any(hasattr(rig.broker, n) for n in ("renew", "extend", "refresh"))
        )
        h1 = rig.request(ttl=timedelta(minutes=5))
        self.assertDenied(
            D.DUPLICATE_LEASE, rig.request, MODEL_REF
        )  # "renewal" while live
        self.assertEqual(rig.backend.resolve_count, 1, "no duplicate value resolved")
        rig.minutes(5)
        self.assertDenied(D.LEASE_EXPIRED, rig.use, h1)
        # re-request after expiry succeeds when policy still grants it
        h2 = rig.request(ttl=timedelta(minutes=5))
        self.assertNotEqual(h1.lease_id, h2.lease_id)
        # policy is re-evaluated: revoke the grant, expire, and the re-request is denied
        rig.broker._policy = policy_from_mapping({"version": 1, "grants": []})
        rig.minutes(5)
        self.assertDenied(D.NO_GRANT, rig.request, MODEL_REF)

    def test_per_task_lease_limit_and_use_limit(self):
        rig = Rig(config=BrokerConfig(max_leases_per_task=2, max_uses_per_lease=3))
        h1 = rig.request(MODEL_REF)
        rig.request(SEARCH_REF)
        self.assertDenied(
            D.TASK_LEASE_LIMIT,
            rig.request,
            SecretRef(Environment.MOCK, Purpose.MODEL_INFERENCE, "mock-model-key-b"),
        )
        for _ in range(3):
            rig.use(h1)
        self.assertDenied(D.USE_LIMIT_EXCEEDED, rig.use, h1)
        self.assertEqual(len(rig.events(E.LEASE_USED)), 3)

    def test_T12_rate_limit_denies_burst_and_raises_alert(self):
        tasks = tuple((f"T-{i}", "R-1", "LR-06") for i in range(10))
        rig = Rig(config=BrokerConfig(agent_rate_limit_per_minute=5), tasks=tasks)
        for i in range(5):
            rig.request(task=f"T-{i}")
        rig.alerts.clear()
        self.assertDenied(D.RATE_LIMITED, rig.request, task="T-5")
        self.assertDenied(D.RATE_LIMITED, rig.request, task="T-6")
        self.assertEqual(
            [a.reason_code for a in rig.alerts], ["rate_limited", "rate_limited"]
        )
        rig.clock.advance(61)
        rig.request(task="T-7")  # window passed

    def test_global_rate_limit(self):
        tasks = tuple((f"T-{i}", "R-1", "LR-06") for i in range(4)) + (
            ("T-X", "R-X", "LR-04"),
        )
        rig = Rig(config=BrokerConfig(global_rate_limit_per_minute=3), tasks=tasks)
        for i in range(3):
            rig.request(task=f"T-{i}")
        self.assertDenied(
            D.GLOBAL_RATE_LIMITED,
            rig.request,
            DB_REF,
            task="T-X",
            run="R-X",
            agent="LR-04",
        )


class MisuseAndBoundary(unittest.TestCase):
    def assertMisuse(self, rig, reason, fn, *a, **k):
        before = len(rig.alerts)
        with self.assertRaises(Denied) as ctx:
            fn(*a, **k)
        self.assertIs(ctx.exception.reason, reason)
        self.assertEqual(len(rig.alerts), before + 1)
        ev = rig.events(E.MISUSE_SUSPECTED)[-1]
        self.assertTrue(ev.alert)
        self.assertEqual(ev.reason_code, reason.value)

    def test_T08_handle_presented_by_other_task_run_or_agent(self):
        rig = Rig(tasks=(("T-1", "R-1", "LR-06"), ("T-2", "R-2", "LR-06")))
        h = rig.request()
        self.assertMisuse(rig, D.CONTEXT_MISMATCH, rig.use, h, task_id="T-2")
        self.assertMisuse(rig, D.CONTEXT_MISMATCH, rig.use, h, run_id="R-2")
        self.assertMisuse(rig, D.CONTEXT_MISMATCH, rig.use, h, agent_id="LR-04")
        self.assertEqual(len(rig.events(E.MISUSE_SUSPECTED)), 3)
        self.assertEqual(len(rig.events(E.LEASE_USED)), 0)
        rig.use(h)  # the legitimate user is unaffected

    def test_T08_tampered_handle_rejected(self):
        rig = Rig(tasks=(("T-1", "R-1", "LR-06"), ("T-2", "R-2", "LR-06")))
        h = rig.request()
        for forged in [
            LeaseHandle(h.lease_id, h.ref, "T-2", "R-2", h.agent_id, h.expires_at),
            LeaseHandle(
                h.lease_id, SEARCH_REF, h.task_id, h.run_id, h.agent_id, h.expires_at
            ),
            LeaseHandle(
                h.lease_id,
                h.ref,
                h.task_id,
                h.run_id,
                h.agent_id,
                h.expires_at + timedelta(days=1),
            ),  # lease extension attempt
        ]:
            with self.subTest(forged=forged.expires_at):
                self.assertMisuse(
                    rig,
                    D.HANDLE_TAMPERED,
                    rig.broker.use,
                    forged,
                    caller=rig.gateways["model-gateway"],
                    context=rig.ctx(forged),
                )

    def test_T08_unknown_lease_id_is_denied_with_alert(self):
        rig = Rig()
        h = rig.request()
        fake = LeaseHandle(
            "A" * 22, h.ref, h.task_id, h.run_id, h.agent_id, h.expires_at
        )
        before = len(rig.alerts)
        with self.assertRaises(Denied) as ctx:
            rig.broker.use(
                fake, caller=rig.gateways["model-gateway"], context=rig.ctx(fake)
            )
        self.assertIs(ctx.exception.reason, D.UNKNOWN_LEASE)
        self.assertEqual(len(rig.alerts), before + 1)

    def test_only_registered_gateways_may_use(self):
        rig = Rig()
        h = rig.request()
        forged_same_id = GatewayIdentity("model-gateway", "x" * 22)
        unregistered = GatewayIdentity("rogue-gateway", "y" * 22)
        no_token = GatewayIdentity("model-gateway")
        for caller in (
            forged_same_id,
            unregistered,
            no_token,
            "model-gateway",
            None,
            object(),
        ):
            with self.subTest(caller=type(caller).__name__):
                self.assertMisuse(
                    rig,
                    D.CALLER_NOT_GATEWAY,
                    rig.broker.use,
                    h,
                    caller=caller,
                    context=rig.ctx(h),
                )  # type: ignore[arg-type]
        self.assertEqual(len(rig.events(E.LEASE_USED)), 0)
        self.assertNotIn(
            rig.gateways["model-gateway"]._token, repr(rig.gateways["model-gateway"])
        )

    def test_gateway_identities_issued_once(self):
        rig = Rig()
        with self.assertRaises(ConfigurationError):
            rig.broker.issue_gateway_identities()

    def test_T09_agent_client_exposes_request_only(self):
        rig = Rig()
        client = rig.broker.agent_client("LR-06")
        public = [n for n in dir(client) if not n.startswith("_")]
        self.assertEqual(public, ["request"])
        for name in (
            "use",
            "revoke",
            "revoke_task",
            "reveal",
            "broker",
            "leased_values",
        ):
            self.assertFalse(hasattr(client, name))
        self.assertFalse(hasattr(client, "__dict__"))
        h = client.request(
            CredentialRequest(
                "T-1", "R-1", "LR-06", MODEL_REF, RequestReason.MODEL_CALL
            )
        )
        self.assertIsInstance(h, LeaseHandle)

    def test_T09_agent_client_cannot_act_as_another_agent(self):
        rig = Rig(tasks=(("T-1", "R-1", "LR-06"), ("T-2", "R-2", "LR-04")))
        client = rig.broker.agent_client("LR-06")
        before = len(rig.alerts)
        with self.assertRaises(Denied) as ctx:
            client.request(
                CredentialRequest(
                    "T-2", "R-2", "LR-04", DB_REF, RequestReason.DB_ACCESS
                )
            )
        self.assertIs(ctx.exception.reason, D.CONTEXT_MISMATCH)
        self.assertEqual(len(rig.alerts), before + 1)
        self.assertEqual(rig.backend.resolve_count, 0)
        with self.assertRaises(Denied):
            client.request("not a request")  # type: ignore[arg-type]

    def test_T09_agent_api_module_does_not_reference_gateway_surface(self):
        src = (
            Path(__file__).resolve().parents[2]
            / "packages"
            / "secrets"
            / "agent_api.py"
        ).read_text()
        tree = ast.parse(src)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported |= {a.name for a in node.names}
                imported.add(node.module or "")
            elif isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
        forbidden = {
            "use",
            "reveal",
            "ScopedSecret",
            "GatewayIdentity",
            "SecretValue",
            "CredentialBroker",
            "InMemoryBackend",
            "backend",
        }
        self.assertFalse(forbidden & names, forbidden & names)
        self.assertFalse(forbidden & imported)
        self.assertFalse(
            {
                m
                for m in imported
                if "broker" in m or "backend" in m or "secret_types" in m
            }
        )


class FailClosed(unittest.TestCase):
    def assertDenied(self, reason, fn, *args, **kw):
        with self.assertRaises(Denied) as ctx:
            fn(*args, **kw)
        self.assertIs(ctx.exception.reason, reason)
        return ctx.exception

    def test_T13_backend_down(self):
        rig = Rig()
        rig.backend.set_healthy(False)
        self.assertDenied(D.BACKEND_UNHEALTHY, rig.request)
        self.assertEqual(len(rig.events(E.BACKEND_UNHEALTHY)), 1)
        self.assertTrue(rig.events(E.BACKEND_UNHEALTHY)[0].alert)
        self.assertEqual(rig.broker.live_lease_count(), 0)
        rig.backend.set_healthy(True)
        rig.request()  # recovers

    def test_T13_backend_health_check_raising_counts_as_unhealthy(self):
        rig = Rig()
        rig.backend.health = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        self.assertDenied(D.BACKEND_UNHEALTHY, rig.request)

    def test_T13_backend_exception_with_canary_never_leaks_through_exception_chain_or_audit(
        self,
    ):
        rig = Rig()
        canary = make_canary()
        rig.backend.fail_next_resolve(
            RuntimeError(f"connection failed for key {canary}")
        )
        exc = self.assertDenied(D.BACKEND_ERROR, rig.request)
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        self.assertNotIn(canary, repr(exc) + str(exc) + repr(exc.args))
        self.assertNotIn(canary, rig.all_audit_text())
        self.assertTrue(rig.events(E.LEASE_DENIED)[-1].alert)
        self.assertEqual(rig.broker.live_lease_count(), 0)

    def test_T13_backend_returning_non_secretvalue_is_refused(self):
        rig = Rig()
        rig.backend.resolve = lambda ref, *, ttl: "plain string value"
        self.assertDenied(D.BACKEND_ERROR, rig.request)
        self.assertEqual(len(rig.broker.leased_values), 0)

    def test_T13_policy_invalid_reload_fails_closed(self):
        rig = Rig()
        rig.request()

        def bad_loader():
            raise PolicyError("invalid")

        with self.assertRaises(PolicyError):
            rig.broker.reload_policy(bad_loader)
        self.assertDenied(D.POLICY_INVALID, rig.request, SEARCH_REF)
        self.assertTrue(rig.events(E.LEASE_DENIED)[-1].alert)
        with self.assertRaises(PolicyError):
            rig.broker.reload_policy(lambda: "not a policy")  # type: ignore[arg-type,return-value]
        rig.broker.reload_policy(lambda: policy_from_mapping(DEFAULT_POLICY))
        rig.request(SEARCH_REF)  # valid policy restores service

    def test_T13_no_policy_at_startup_denies_everything(self):
        rig = Rig()
        broker = CredentialBroker(
            backend=rig.backend,
            policy=None,
            task_registry=rig.registry,
            clock=rig.clock,
            audit_sink=rig.sink,
        )
        with self.assertRaises(Denied) as ctx:
            broker.request(
                CredentialRequest(
                    "T-1", "R-1", "LR-06", MODEL_REF, RequestReason.MODEL_CALL
                )
            )
        self.assertIs(ctx.exception.reason, D.POLICY_INVALID)

    def test_T13_clock_faults(self):
        rig = Rig()
        h = rig.request()
        rig.clock.fail_with = RuntimeError("clock unavailable")
        self.assertDenied(D.CLOCK_FAULT, rig.request, SEARCH_REF)
        self.assertDenied(D.CLOCK_FAULT, rig.use, h)
        rig.clock.fail_with = None
        rig.clock.set_monotonic(
            rig.clock.monotonic() - 100
        )  # monotonic clock went backwards
        self.assertDenied(D.CLOCK_FAULT, rig.request, SEARCH_REF)
        self.assertDenied(D.CLOCK_FAULT, rig.use, h)
        self.assertEqual(len(rig.backend.revoked), 0)
        for bad in (float("nan"), float("inf"), "1", True):
            rig.clock.set_monotonic(0)
            rig.clock.monotonic = lambda b=bad: b  # type: ignore[method-assign]
            self.assertDenied(D.CLOCK_FAULT, rig.request, SEARCH_REF)

    def test_revocation_still_works_during_clock_fault(self):
        rig = Rig()
        rig.request()
        rig.clock.fail_with = RuntimeError("clock unavailable")
        self.assertEqual(
            rig.broker.revoke_task("T-1", reason_code=RevokeReason.STOP), 1
        )
        self.assertEqual(rig.broker.live_lease_count(), 0)

    def test_audit_sink_failure_means_no_credential(self):
        rig = Rig()

        class Broken:
            def emit(self, event):
                raise OSError("disk full")

        rig.broker.audit_sink = Broken()
        self.assertDenied(D.INTERNAL_ERROR, rig.request)
        self.assertEqual(rig.broker.live_lease_count(), 0)
        self.assertEqual(len(rig.broker.leased_values), 0)

    def test_audit_failure_on_issue_rolls_back_the_lease(self):
        rig = Rig()

        class FailOnIssue:
            def __init__(self, inner):
                self.inner = inner

            def emit(self, event):
                if event.event_type == "lease_issued":
                    raise OSError("disk full")
                self.inner.emit(event)

        rig.broker.audit_sink = FailOnIssue(rig.sink)
        self.assertDenied(D.INTERNAL_ERROR, rig.request)
        self.assertEqual(rig.broker.live_lease_count(), 0)
        self.assertEqual(len(rig.broker.leased_values), 0)
        self.assertTrue(
            rig.backend.revoked,
            "provider-side revoke attempted for the rolled-back lease",
        )

    def test_backend_revoke_failure_still_kills_local_lease_and_alerts(self):
        rig = Rig()
        h = rig.request()
        rig.backend.revoke = lambda ref, lease_id: (_ for _ in ()).throw(
            OSError("provider down")
        )
        self.assertTrue(
            rig.broker.revoke(h.lease_id, reason_code=RevokeReason.OWNER_ACTION)
        )
        self.assertIs(rig.broker.lease_state(h.lease_id), LeaseState.REVOKED)
        ev = rig.events(E.BACKEND_UNHEALTHY)
        self.assertEqual(len(ev), 1)
        self.assertTrue(ev[0].alert)

    def test_alert_handler_failure_does_not_break_the_broker(self):
        rig = Rig()
        rig.broker._alert_handler = lambda ev: 1 / 0
        with self.assertRaises(Denied):
            rig.request(MODEL_REF, task="T-none")

    def test_falsy_registry_answer_and_non_request_fail_closed(self):
        rig = Rig()
        rig.registry.is_live = lambda *a: None  # falsy answer -> not live
        self.assertDenied(D.TASK_NOT_LIVE, rig.request)
        self.assertDenied(D.MALFORMED_REQUEST, rig.broker.request, object())  # type: ignore[arg-type]


class TimeSource(unittest.TestCase):
    def test_T29_wall_clock_jumps_do_not_extend_or_shorten_a_lease(self):
        rig = Rig()
        h = rig.request(ttl=timedelta(minutes=5))
        rig.clock.jump_wall(86400)  # wall clock jumps a day ahead
        rig.clock.advance(60)
        rig.use(h)  # still alive: only 60 monotonic seconds passed
        rig.clock.jump_wall(-10 * 86400)  # and far behind
        rig.clock.advance(60)
        rig.use(h)
        rig.clock.advance(180)  # total 300 monotonic seconds
        with self.assertRaises(Denied) as ctx:
            rig.use(h)
        self.assertIs(ctx.exception.reason, D.LEASE_EXPIRED)

    def test_T29_audit_records_wall_clock_in_utc(self):
        rig = Rig()
        rig.request()
        ts = rig.events(E.LEASE_ISSUED)[0].timestamp
        self.assertTrue(ts.endswith("+00:00"), ts)


class Concurrency(unittest.TestCase):
    def run_threads(self, n, fn):
        errors, barrier = [], threading.Barrier(n)

        def runner(i):
            barrier.wait()
            try:
                fn(i)
            except Denied:
                pass
            except BaseException as exc:  # pragma: no cover - would fail the test  # noqa: BLE001 - fail-safe boundary: must never propagate
                errors.append(exc)

        threads = [threading.Thread(target=runner, args=(i,)) for i in range(n)]
        [t.start() for t in threads]
        [t.join(10) for t in threads]
        self.assertEqual(errors, [])

    def test_T28_parallel_duplicates_yield_exactly_one_lease(self):
        rig = Rig()
        self.run_threads(24, lambda i: rig.request())
        self.assertEqual(rig.broker.live_lease_count("T-1"), 1)
        self.assertEqual(rig.backend.resolve_count, 1)
        self.assertEqual(len(rig.events(E.LEASE_ISSUED)), 1)

    def test_T28_parallel_requests_never_exceed_per_task_limit(self):
        rig = Rig(config=BrokerConfig(max_leases_per_task=2))
        refs = [
            MODEL_REF,
            SEARCH_REF,
            SecretRef(Environment.MOCK, Purpose.MODEL_INFERENCE, "mock-model-key-b"),
            SecretRef(Environment.MOCK, Purpose.MODEL_INFERENCE, "mock-model-key-c"),
        ]
        self.run_threads(32, lambda i: rig.request(refs[i % 4]))
        self.assertEqual(rig.broker.live_lease_count("T-1"), 2)

    def test_T28_revocation_race_never_leaves_a_live_lease(self):
        for _ in range(20):
            rig = Rig(config=BrokerConfig(max_leases_per_task=4))
            refs = [
                MODEL_REF,
                SEARCH_REF,
                SecretRef(
                    Environment.MOCK, Purpose.MODEL_INFERENCE, "mock-model-key-b"
                ),
                SecretRef(
                    Environment.MOCK, Purpose.MODEL_INFERENCE, "mock-model-key-c"
                ),
            ]

            def work(i):
                if i == 0:
                    rig.registry.end_task("T-1", TaskState.COMPLETED, broker=rig.broker)  # noqa: B023 - closure invoked within the same iteration
                else:
                    rig.request(refs[i % 4])  # noqa: B023 - closure invoked within the same iteration

            self.run_threads(16, work)
            self.assertEqual(rig.broker.live_lease_count("T-1"), 0)
            self.assertEqual(len(rig.broker.leased_values), 0)

    def test_T28_parallel_use_counts_are_exact(self):
        rig = Rig(config=BrokerConfig(max_uses_per_lease=10))
        h = rig.request()
        ok = []

        def work(i):
            with rig.use(h):
                ok.append(1)

        self.run_threads(30, work)
        self.assertEqual(len(ok), 10)
        self.assertEqual(len(rig.events(E.LEASE_USED)), 10)


if __name__ == "__main__":
    unittest.main()
