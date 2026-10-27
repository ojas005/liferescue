"""LR 08 N-05: DEMO_REQUIRE_TOKEN=1 forces the demo token even on localhost; open gate warns about tunnels."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.access import TUNNEL_WARNING, InsecureBindError, enforce_bind_policy
from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app

TOKEN = "unit-test-n05-token-Lk42v"  # test-only value
ROOT = Path(__file__).resolve().parents[2]


class TestN05RequireToken(unittest.TestCase):
    def test_require_token_on_localhost_without_token_refuses(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            with self.subTest(host=host), self.assertRaises(InsecureBindError):
                enforce_bind_policy(host, None, require_token=True)
        enforce_bind_policy("127.0.0.1", TOKEN, require_token=True)

    def test_require_token_gates_localhost_api(self):
        reset_for_tests(":memory:")
        client = TestClient(
            create_app(
                Settings(
                    db_path=":memory:",
                    ai_provider="mock",
                    demo_access_token=TOKEN,
                    demo_require_token=True,
                )
            )
        )
        self.assertEqual(client.get("/incidents").status_code, 401)
        self.assertEqual(
            client.get("/incidents", headers={"X-Demo-Token": TOKEN}).status_code, 200
        )

    def _run(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("DEMO_")}
        env.update(
            HOST="127.0.0.1", PORT="1", DB_PATH=":memory:", AI_PROVIDER="mock", **extra
        )
        return subprocess.run(
            [sys.executable, "apps/api/run.py"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_run_py_refuses_with_require_flag_and_no_token(self):
        p = self._run(DEMO_REQUIRE_TOKEN="1")
        self.assertNotEqual(
            p.returncode, 0
        )  # fails closed (import-time app or run.py check)
        self.assertIn("DEMO_REQUIRE_TOKEN", p.stderr)

    def test_tunnel_warning_text(self):
        self.assertIn("DEMO_ACCESS_TOKEN", TUNNEL_WARNING)
        self.assertIn("DEMO_REQUIRE_TOKEN=1", TUNNEL_WARNING)
        self.assertIn("tunnel", TUNNEL_WARNING)


if __name__ == "__main__":
    unittest.main()
