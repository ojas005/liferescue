"""KAN-50: per-client-IP rate limit on cost/abuse-sensitive routes."""

import multiprocessing
import os
import sqlite3
import tempfile
import threading
import unittest

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app
from apps.api.ratelimit import (
    RateLimiter,
    RateLimitMiddleware,
    RateLimitUnavailable,
    is_limited,
    store_path_for,
)
from packages.domain.ai import NVIDIAAIProvider, create_ai_provider
from packages.domain.models import Incident

BODY = {"title": "t", "description": "I twisted my ankle", "location": "Park"}


def _client(**kw) -> TestClient:
    reset_for_tests(":memory:")
    return TestClient(
        create_app(Settings(db_path=":memory:", ai_provider="mock", **kw))
    )


class TestRateLimit(unittest.TestCase):
    def test_429_after_limit_with_generic_message(self):
        c = _client(rate_limit_requests=3, rate_limit_window_s=60)
        for _ in range(3):
            self.assertEqual(c.post("/incidents", json=BODY).status_code, 201)
        r = c.post("/incidents", json=BODY)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["error"], "TooManyRequests")
        self.assertIn("Retry-After", r.headers)
        self.assertNotIn("testclient", r.text)
        # all limited routes share the per-IP budget
        self.assertEqual(
            c.post("/demo/scenarios/scenario_medical/run").status_code, 429
        )
        self.assertEqual(c.post("/demo/reset").status_code, 429)

    def test_unlimited_routes_unaffected(self):
        c = _client(rate_limit_requests=1, rate_limit_window_s=60)
        c.post("/incidents", json=BODY)
        self.assertEqual(c.post("/incidents", json=BODY).status_code, 429)
        for _ in range(5):
            self.assertEqual(c.get("/health").status_code, 200)
            self.assertEqual(c.get("/readiness").status_code, 200)
            self.assertEqual(c.get("/audit/events").status_code, 200)

    def test_zero_disables(self):
        c = _client(rate_limit_requests=0)
        for _ in range(25):
            self.assertEqual(c.post("/incidents", json=BODY).status_code, 201)

    def test_xff_ignored_unless_trust_proxy(self):
        c = _client(rate_limit_requests=1, rate_limit_window_s=60)
        self.assertEqual(
            c.post(
                "/incidents", json=BODY, headers={"X-Forwarded-For": "1.1.1.1"}
            ).status_code,
            201,
        )
        # spoofed XFF must not grant a fresh budget when proxy is not trusted
        self.assertEqual(
            c.post(
                "/incidents", json=BODY, headers={"X-Forwarded-For": "2.2.2.2"}
            ).status_code,
            429,
        )

    def test_normal_use_under_limit(self):
        c = _client(rate_limit_requests=5, rate_limit_window_s=60)
        r = c.post("/incidents", json=BODY)
        self.assertEqual(r.status_code, 201)
        iid = r.json()["incident_id"]
        self.assertEqual(c.post(f"/incidents/{iid}/analyze").status_code, 200)
        self.assertEqual(c.get(f"/incidents/{iid}").status_code, 200)

    def test_repeated_requests_counted_until_429(self):
        c = _client(rate_limit_requests=4, rate_limit_window_s=60)
        codes = [c.post("/incidents", json=BODY).status_code for _ in range(6)]
        self.assertEqual(codes, [201, 201, 201, 201, 429, 429])

    def test_trust_proxy_uses_rightmost_hop(self):
        c = _client(rate_limit_requests=1, rate_limit_window_s=60, trust_proxy=True)
        # proxy appended 9.9.9.9; the left hop is client-supplied
        h = {"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}
        self.assertEqual(c.post("/incidents", json=BODY, headers=h).status_code, 201)
        self.assertEqual(c.post("/incidents", json=BODY, headers=h).status_code, 429)
        # a different real client (different rightmost hop) has its own budget
        h2 = {"X-Forwarded-For": "8.8.8.8"}
        self.assertEqual(c.post("/incidents", json=BODY, headers=h2).status_code, 201)

    def test_spoofed_headers_do_not_reset_bucket_behind_proxy(self):
        c = _client(rate_limit_requests=2, rate_limit_window_s=60, trust_proxy=True)
        real = "9.9.9.9"
        for _ in range(2):
            self.assertEqual(
                c.post(
                    "/incidents", json=BODY, headers={"X-Forwarded-For": real}
                ).status_code,
                201,
            )
        spoofs = [
            {"X-Forwarded-For": f"5.5.5.5, {real}"},
            {"X-Forwarded-For": f"6.6.6.6, 7.7.7.7, {real}"},
            {"X-Forwarded-For": real, "X-Real-IP": "4.4.4.4"},
            {"X-Forwarded-For": f"10.0.0.1,{real}", "X-Real-IP": "3.3.3.3"},
            {"X-Forwarded-For": f"not-an-ip, {real}"},
        ]
        for h in spoofs:
            self.assertEqual(
                c.post("/incidents", json=BODY, headers=h).status_code, 429, h
            )

    def test_spoofed_headers_ignored_without_trust_proxy(self):
        c = _client(rate_limit_requests=1, rate_limit_window_s=60)
        self.assertEqual(c.post("/incidents", json=BODY).status_code, 201)
        for h in (
            {"X-Forwarded-For": "2.2.2.2"},
            {"X-Real-IP": "3.3.3.3"},
            {"X-Forwarded-For": "1.1.1.1, 2.2.2.2", "X-Real-IP": "3.3.3.3"},
        ):
            self.assertEqual(
                c.post("/incidents", json=BODY, headers=h).status_code, 429, h
            )

    def test_invalid_rightmost_hop_falls_back_to_peer(self):
        c = _client(rate_limit_requests=1, rate_limit_window_s=60, trust_proxy=True)
        self.assertEqual(c.post("/incidents", json=BODY).status_code, 201)
        h = {"X-Forwarded-For": "garbage"}
        self.assertEqual(c.post("/incidents", json=BODY, headers=h).status_code, 429)

    def test_window_resets(self):
        t = [0.0]
        rl = RateLimiter(2, 10, clock=lambda: t[0])
        self.assertTrue(rl.allow("a")[0])
        self.assertTrue(rl.allow("a")[0])
        ok, retry = rl.allow("a")
        self.assertFalse(ok)
        self.assertGreaterEqual(retry, 1)
        t[0] = 10.0
        self.assertTrue(rl.allow("a")[0])

    def test_route_matching(self):
        self.assertTrue(is_limited("POST", "/incidents"))
        self.assertTrue(is_limited("POST", "/incidents/inc_1/analyze"))
        self.assertTrue(is_limited("POST", "/demo/scenarios/x/run"))
        self.assertTrue(is_limited("POST", "/demo/reset"))
        self.assertFalse(is_limited("GET", "/incidents"))
        self.assertFalse(is_limited("POST", "/contacts"))


class TestCloudflareClientIp(unittest.TestCase):
    def test_cf_connecting_ip_is_bucket_key_behind_proxy(self):
        c = _client(rate_limit_requests=2, rate_limit_window_s=60, trust_proxy=True)
        # Render+Cloudflare: rightmost XFF hop is a varying proxy IP; CF-Connecting-IP is the client
        codes = [
            c.post(
                "/incidents",
                json=BODY,
                headers={
                    "CF-Connecting-IP": "203.0.113.9",
                    "X-Forwarded-For": f"6.6.6.6, 203.0.113.9, 10.0.0.{i}",
                },
            ).status_code
            for i in range(4)
        ]
        self.assertEqual(codes, [201, 201, 429, 429])
        other = {"CF-Connecting-IP": "198.51.100.7", "X-Forwarded-For": "10.0.0.9"}
        self.assertEqual(
            c.post("/incidents", json=BODY, headers=other).status_code, 201
        )

    def test_cf_header_ignored_without_trust_proxy(self):
        c = _client(rate_limit_requests=1, rate_limit_window_s=60)
        self.assertEqual(c.post("/incidents", json=BODY).status_code, 201)
        h = {"CF-Connecting-IP": "198.51.100.7"}
        self.assertEqual(c.post("/incidents", json=BODY, headers=h).status_code, 429)

    def test_invalid_cf_header_falls_back(self):
        c = _client(rate_limit_requests=1, rate_limit_window_s=60, trust_proxy=True)
        h = {"CF-Connecting-IP": "not-an-ip", "X-Forwarded-For": "9.9.9.9"}
        self.assertEqual(c.post("/incidents", json=BODY, headers=h).status_code, 201)
        self.assertEqual(c.post("/incidents", json=BODY, headers=h).status_code, 429)


class TestSharedAcrossWorkers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "rl.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_limiters_share_one_budget(self):
        a = RateLimiter(3, 60, db_path=self.path)
        b = RateLimiter(3, 60, db_path=self.path)
        self.assertTrue(a.allow("ip:1")[0])
        self.assertTrue(b.allow("ip:1")[0])
        self.assertTrue(a.allow("ip:1")[0])
        self.assertFalse(b.allow("ip:1")[0])
        self.assertFalse(a.allow("ip:1")[0])

    def test_separate_processes_share_one_budget(self):
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(4) as pool:
            results = pool.map(_hit, [self.path] * 20)
        self.assertEqual(sum(results), 7)

    def test_store_path(self):
        self.assertEqual(store_path_for(":memory:"), ":memory:")
        self.assertEqual(store_path_for("./x.db"), "./x.db.ratelimit")


class TestGlobalModelCeiling(unittest.TestCase):
    def test_gate_closed_falls_back_without_network(self):
        p = NVIDIAAIProvider(api_key="k", call_gate=lambda: "global_rate_limit")
        inc = Incident(user_id="u", title="t", description="chest pain", location="x")
        res = p.analyze_emergency(inc)
        self.assertIn("global_rate_limit", res.provider_name)

    def test_factory_caps_calls_per_minute(self):
        with tempfile.TemporaryDirectory() as d:
            s = Settings(
                db_path=os.path.join(d, "a.db"),
                ai_provider="nvidia",
                nebius_api_key="k",
                ai_global_calls_per_minute=2,
            )
            gate = create_ai_provider("nvidia", s)._call_gate
            gate2 = create_ai_provider("nvidia", s)._call_gate  # another worker
            self.assertEqual(
                [gate(), gate2(), gate(), gate2()],
                [None, None, "global_rate_limit", "global_rate_limit"],
            )

    def test_default_ceiling_is_set(self):
        self.assertEqual(Settings().ai_global_calls_per_minute, 30)


class TestDailyBudget(unittest.TestCase):
    def _settings(self, d, **kw):
        return Settings(
            db_path=os.path.join(d, "a.db"),
            ai_provider="nvidia",
            nebius_api_key="k",
            **kw,
        )

    def test_default_daily_budget(self):
        self.assertEqual(Settings().ai_daily_call_budget, 500)

    def test_budget_exhausted_across_instances(self):
        with tempfile.TemporaryDirectory() as d:
            s = self._settings(d, ai_global_calls_per_minute=0, ai_daily_call_budget=3)
            g1 = create_ai_provider("nvidia", s)._call_gate
            g2 = create_ai_provider("nvidia", s)._call_gate  # another worker
            self.assertEqual(
                [g1(), g2(), g1(), g2(), g1()],
                [None, None, None, "daily_budget_exhausted", "daily_budget_exhausted"],
            )

    def test_exhausted_budget_never_calls_nebius(self):
        import httpx

        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(500)

        with tempfile.TemporaryDirectory() as d:
            s = self._settings(d, ai_daily_call_budget=1)
            p = create_ai_provider("nvidia", s)
            p._transport = httpx.MockTransport(handler)
            inc = Incident(
                user_id="u", title="t", description="chest pain", location="x"
            )
            p.analyze_emergency(inc)  # uses the single budgeted call
            self.assertEqual(len(calls), 1)
            res = p.analyze_emergency(inc)
            self.assertEqual(len(calls), 1)
            self.assertIn("mock_fallback: daily_budget_exhausted", res.provider_name)

    def test_zero_budget_disables_live_calls(self):
        with tempfile.TemporaryDirectory() as d:
            p = create_ai_provider("nvidia", self._settings(d, ai_daily_call_budget=0))
            inc = Incident(
                user_id="u", title="t", description="chest pain", location="x"
            )
            self.assertIn(
                "mock_fallback: daily_budget_exhausted",
                p.analyze_emergency(inc).provider_name,
            )


class TestFailClosed(unittest.TestCase):
    BAD = "/nonexistent-dir-kan50/x.db.ratelimit"

    def test_store_error_raises_unavailable(self):
        rl = RateLimiter(5, 60, db_path=self.BAD)
        with self.assertRaises(RateLimitUnavailable):
            rl.allow("ip:1")

    def test_middleware_returns_503_not_open(self):
        hits = []

        async def ok(request):
            hits.append(1)
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/incidents", ok, methods=["POST", "GET"])])
        app.add_middleware(
            RateLimitMiddleware, limiter=RateLimiter(5, 60, db_path=self.BAD)
        )
        c = TestClient(app)
        r = c.post("/incidents")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["detail"], "Temporarily unavailable, try again.")
        self.assertNotIn("sqlite", r.text.lower())
        self.assertEqual(hits, [])  # handler never reached
        self.assertEqual(c.get("/incidents").status_code, 200)  # unlimited route

    def test_ai_gate_error_uses_labelled_mock(self):
        s = Settings(
            db_path="/nonexistent-dir-kan50/x.db",
            ai_provider="nvidia",
            nebius_api_key="k",
            ai_global_calls_per_minute=5,
        )
        p = create_ai_provider("nvidia", s)
        self.assertEqual(p._call_gate(), "rate_limit_unavailable")
        inc = Incident(user_id="u", title="t", description="chest pain", location="x")
        self.assertIn(
            "mock_fallback: rate_limit_unavailable",
            p.analyze_emergency(inc).provider_name,
        )

    def test_lock_contention_waits_instead_of_failing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rl.sqlite")
            rl = RateLimiter(5, 60, db_path=path)
            blocker = sqlite3.connect(
                path, isolation_level=None, check_same_thread=False
            )
            blocker.execute("BEGIN IMMEDIATE")
            t = threading.Timer(0.5, lambda: blocker.execute("COMMIT"))
            t.start()
            try:
                self.assertTrue(rl.allow("ip:1")[0])
            finally:
                t.join()
                blocker.close()


class TestConcurrencyAccounting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "rl.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def test_threads_never_exceed_limit_and_account_exactly(self):
        rl = RateLimiter(25, 60, db_path=self.path)
        results: list[bool] = []
        errors: list[BaseException] = []
        mu = threading.Lock()

        def worker():
            for _ in range(10):
                try:
                    ok = rl.allow("ip:t")[0]
                except BaseException as e:  # noqa: BLE001 - recorded and asserted
                    errors.append(e)
                    continue
                with mu:
                    results.append(ok)

        ts = [threading.Thread(target=worker) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errors, [])
        allowed = sum(results)
        self.assertEqual(len(results), 80)  # allowed + rejected == attempts
        self.assertEqual(allowed, 25)
        self.assertEqual(rl.count("ip:t"), allowed)

    def test_instances_in_threads_share_budget(self):
        limiters = [RateLimiter(10, 60, db_path=self.path) for _ in range(4)]
        out: list[bool] = []
        mu = threading.Lock()

        def worker(rl):
            for _ in range(8):
                ok = rl.allow("ip:i")[0]
                with mu:
                    out.append(ok)

        ts = [threading.Thread(target=worker, args=(rl,)) for rl in limiters]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual((len(out), sum(out)), (32, 10))
        self.assertEqual(limiters[0].count("ip:i"), 10)

    def test_processes_account_exactly(self):
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(6) as pool:
            res = pool.map(_burst, [self.path] * 6)
        self.assertEqual([e for _, _, e in res], [""] * 6)  # no uncaught lock errors
        allowed = sum(a for a, _, _ in res)
        rejected = sum(r for _, r, _ in res)
        self.assertEqual(allowed + rejected, 6 * 10)
        self.assertEqual(allowed, 15)
        self.assertEqual(RateLimiter(15, 60, db_path=self.path).count("ip:p"), 15)


class TestTransientLocks(unittest.TestCase):
    def test_bounded_retry_then_success(self):
        rl = RateLimiter(5, 60)
        real = rl._allow
        calls = []

        def flaky(key):
            calls.append(1)
            if len(calls) < 3:
                raise sqlite3.OperationalError("database is locked")
            return real(key)

        rl._allow = flaky  # type: ignore[method-assign]
        self.assertTrue(rl.allow("k")[0])
        self.assertEqual(len(calls), 3)

    def test_persistent_lock_is_finite_and_fails_closed(self):
        rl = RateLimiter(5, 60)
        calls = []

        def locked(key):
            calls.append(1)
            raise sqlite3.OperationalError("database is locked")

        rl._allow = locked  # type: ignore[method-assign]
        with self.assertRaises(RateLimitUnavailable):
            rl.allow("k")
        self.assertEqual(len(calls), 3)

    def test_persistent_lock_gives_503_retry_after_in_app(self):
        c = _client(rate_limit_requests=5, rate_limit_window_s=60)
        mw = None
        stack = c.app.middleware_stack  # build the stack
        del stack
        for m in c.app.user_middleware:
            if m.cls is RateLimitMiddleware:
                mw = m
        self.assertIsNotNone(mw)
        limiter = mw.kwargs["limiter"]

        def locked(key):
            raise sqlite3.OperationalError("database is locked")

        limiter._allow = locked
        r = c.post("/incidents", json=BODY)
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.headers.get("Retry-After"), "5")
        self.assertEqual(r.json()["error"], "ServiceUnavailable")
        self.assertEqual(c.get("/health").status_code, 200)


class TestStartup(unittest.TestCase):
    def test_app_starts_with_file_db_and_creates_store(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "app.db")
            reset_for_tests(":memory:")
            app = create_app(
                Settings(db_path=db, ai_provider="mock", rate_limit_requests=2)
            )
            with TestClient(app) as c:
                self.assertEqual(c.get("/health").status_code, 200)
                self.assertEqual(c.post("/incidents", json=BODY).status_code, 201)
            self.assertTrue(os.path.exists(db + ".ratelimit"))


def _burst(path: str) -> tuple[int, int, str]:
    a = r = 0
    try:
        rl = RateLimiter(15, 60, db_path=path)
        for _ in range(10):
            if rl.allow("ip:p")[0]:
                a += 1
            else:
                r += 1
    except BaseException as e:  # noqa: BLE001 - reported to the parent test
        return a, r, repr(e)
    return a, r, ""


def _hit(path: str) -> int:
    return int(RateLimiter(7, 60, db_path=path).allow("ip:shared")[0])


if __name__ == "__main__":
    unittest.main()
