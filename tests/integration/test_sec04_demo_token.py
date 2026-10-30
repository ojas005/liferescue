"""LR 08 SEC-04 (High) per Ojas's decision: DEMO_ACCESS_TOKEN gate."""

import io
import logging
import os
import subprocess
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.access import InsecureBindError, enforce_bind_policy
from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app

TOKEN = "unit-test-demo-token-Zq81x"  # test-only value
ROOT = Path(__file__).resolve().parents[2]


class TestTokenGate(unittest.TestCase):
    def setUp(self):
        reset_for_tests(":memory:")
        self.log = io.StringIO()
        self.handler = logging.StreamHandler(self.log)
        logging.getLogger().addHandler(self.handler)
        logging.getLogger().setLevel(logging.DEBUG)
        self.client = TestClient(
            create_app(
                Settings(
                    db_path=":memory:", ai_provider="mock", demo_access_token=TOKEN
                )
            )
        )

    def tearDown(self):
        logging.getLogger().removeHandler(self.handler)

    def test_missing_token_401(self):
        for path in (
            "/incidents",
            "/audit/events",
            "/readiness?user_id=usr_demo",
            "/docs",
            "/openapi.json",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post("/demo/reset").status_code, 401)

    def test_wrong_token_401(self):
        for bad in ("nope", TOKEN[:-1], TOKEN + "x", ""):
            with self.subTest(bad=bad):
                self.assertEqual(
                    self.client.get(
                        "/incidents", headers={"X-Demo-Token": bad}
                    ).status_code,
                    401,
                )

    def test_right_token_ok_and_health_public(self):
        self.assertEqual(
            self.client.get("/incidents", headers={"X-Demo-Token": TOKEN}).status_code,
            200,
        )
        r = self.client.post(
            "/demo/scenarios/scenario_medical/run", headers={"X-Demo-Token": TOKEN}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)

    def test_quoted_and_whitespace_token_variants_accepted(self):
        variants = [
            f'"{TOKEN}"',
            f"'{TOKEN}'",
            f"  {TOKEN}  ",
            f"\r\n{TOKEN}\n",
            f'  "{TOKEN}" \r\n',
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                r = self.client.get("/incidents", headers={"X-Demo-Token": variant})
                self.assertEqual(r.status_code, 200)

    def test_server_configured_with_quotes_or_whitespace(self):
        for conf_variant in (
            f'"{TOKEN}"',
            f"'{TOKEN}'",
            f"  {TOKEN}\n",
            f'  "{TOKEN}"  ',
        ):
            with self.subTest(conf_variant=conf_variant):
                reset_for_tests(":memory:")
                c = TestClient(
                    create_app(
                        Settings(
                            db_path=":memory:",
                            ai_provider="mock",
                            demo_access_token=conf_variant,
                        )
                    )
                )
                # Client supplies standard clean token without quotes
                self.assertEqual(
                    c.get("/incidents", headers={"X-Demo-Token": TOKEN}).status_code,
                    200,
                )

    def test_authorization_bearer_header_accepted(self):
        r = self.client.get("/incidents", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(r.status_code, 200)

    def test_query_param_token_accepted(self):
        r = self.client.get(f"/incidents?token={TOKEN}")
        self.assertEqual(r.status_code, 200)
        r2 = self.client.get(f"/incidents?demo_token={TOKEN}")
        self.assertEqual(r2.status_code, 200)

    def test_demo_auth_status_endpoint(self):
        self.assertEqual(self.client.get("/demo/auth/status").status_code, 401)
        self.assertEqual(
            self.client.get(
                "/demo/auth/status", headers={"X-Demo-Token": "bad-token"}
            ).status_code,
            401,
        )
        r = self.client.get("/demo/auth/status", headers={"X-Demo-Token": TOKEN})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data.get("authenticated"))

    def test_token_never_in_responses_or_logs(self):
        bodies = []
        for headers in ({}, {"X-Demo-Token": "wrong"}, {"X-Demo-Token": TOKEN}):
            for path in ("/incidents", "/incidents/does-not-exist", "/health"):
                r = self.client.get(path, headers=headers)
                bodies.append(r.text + str(dict(r.headers)))
        r = self.client.post(
            "/incidents", headers={"X-Demo-Token": TOKEN}, json={"bad": TOKEN}
        )
        bodies.append(r.text)
        logging.getLogger("liferescue.test").warning("echo %s", TOKEN)
        self.assertNotIn(TOKEN, "".join(bodies))
        self.assertNotIn(TOKEN, self.log.getvalue())
        self.assertNotIn(TOKEN, repr(Settings(demo_access_token=TOKEN)))


class TestBindPolicy(unittest.TestCase):
    def test_policy(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            enforce_bind_policy(host, None)
        for host in ("0.0.0.0", "192.168.1.5", "example.com", "::"):
            with self.subTest(host=host), self.assertRaises(InsecureBindError):
                enforce_bind_policy(host, None)
            enforce_bind_policy(host, TOKEN)
        with self.assertRaises(InsecureBindError):
            enforce_bind_policy("0.0.0.0", "   ")

    def test_create_app_refuses(self):
        with self.assertRaises(InsecureBindError):
            create_app(Settings(db_path=":memory:", host="0.0.0.0"))

    def test_run_py_refuses_startup(self):
        env = {k: v for k, v in os.environ.items() if k.upper() != "DEMO_ACCESS_TOKEN"}
        env.update(HOST="0.0.0.0", DB_PATH=":memory:")
        p = subprocess.run(
            [sys.executable, "apps/api/run.py"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("DEMO_ACCESS_TOKEN", p.stderr)

    def test_localhost_without_token_stays_open(self):
        reset_for_tests(":memory:")
        c = TestClient(create_app(Settings(db_path=":memory:", host="127.0.0.1")))
        self.assertEqual(c.get("/incidents").status_code, 200)

    def test_offloopback_server_without_token_refused_at_runtime(self):
        reset_for_tests(":memory:")
        c = TestClient(
            create_app(Settings(db_path=":memory:")), base_url="http://10.0.0.5"
        )
        # TestClient reports scope["server"] from base_url host
        self.assertEqual(c.get("/incidents").status_code, 503)
        self.assertEqual(c.get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
