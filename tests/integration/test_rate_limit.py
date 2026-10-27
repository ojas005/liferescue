"""KAN-50: per-client-IP rate limit on cost/abuse-sensitive routes."""

import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app
from apps.api.ratelimit import RateLimiter, is_limited

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

    def test_xff_first_hop_when_trust_proxy(self):
        c = _client(rate_limit_requests=1, rate_limit_window_s=60, trust_proxy=True)
        self.assertEqual(
            c.post(
                "/incidents",
                json=BODY,
                headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"},
            ).status_code,
            201,
        )
        self.assertEqual(
            c.post(
                "/incidents",
                json=BODY,
                headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.2"},
            ).status_code,
            429,
        )
        self.assertEqual(
            c.post(
                "/incidents", json=BODY, headers={"X-Forwarded-For": "3.3.3.3"}
            ).status_code,
            201,
        )

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


if __name__ == "__main__":
    unittest.main()
