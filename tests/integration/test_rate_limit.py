"""KAN-50: per-client-IP rate limit on cost/abuse-sensitive routes."""

import multiprocessing
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app
from apps.api.ratelimit import RateLimiter, is_limited, store_path_for
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
        p = NVIDIAAIProvider(api_key="k", call_gate=lambda: False)
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
                [gate(), gate2(), gate(), gate2()], [True, True, False, False]
            )

    def test_default_ceiling_is_set(self):
        self.assertEqual(Settings().ai_global_calls_per_minute, 30)


def _hit(path: str) -> int:
    return int(RateLimiter(7, 60, db_path=path).allow("ip:shared")[0])


if __name__ == "__main__":
    unittest.main()
