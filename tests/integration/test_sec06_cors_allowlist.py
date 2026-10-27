"""LR 08 SEC-06 (High): CORS is an explicit allowlist; arbitrary origins are not reflected."""

import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app

PREFLIGHT = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}


class TestSec06(unittest.TestCase):
    def setUp(self):
        reset_for_tests(":memory:")
        self.client = TestClient(create_app(Settings(db_path=":memory:", ai_provider="mock", port=8000)))

    def test_evil_origin_not_reflected(self):
        for method in ("get", "options"):
            with self.subTest(method=method):
                h = {"Origin": "https://evil.example", **(PREFLIGHT if method == "options" else {})}
                r = getattr(self.client, method)("/incidents", headers=h)
                self.assertNotIn("access-control-allow-origin", {k.lower() for k in r.headers})
                self.assertNotEqual(r.headers.get("access-control-allow-credentials"), "true")

    def test_localhost_allowed(self):
        for origin in ("http://localhost:8000", "http://127.0.0.1:8000"):
            with self.subTest(origin=origin):
                r = self.client.options("/incidents", headers={"Origin": origin, **PREFLIGHT})
                self.assertEqual(r.headers.get("access-control-allow-origin"), origin)
                self.assertIsNone(r.headers.get("access-control-allow-credentials"))

    def test_wildcard_setting_is_ignored(self):
        self.assertEqual(Settings(cors_origins="*").cors_allowlist(), [])
        self.assertEqual(Settings(cors_origins="https://a.example/, *").cors_allowlist(), ["https://a.example"])


if __name__ == "__main__":
    unittest.main()
