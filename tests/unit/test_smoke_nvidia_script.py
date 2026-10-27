"""KAN-50 P1: scripts/smoke_nvidia.py is safe to run without a key and never prints secrets."""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestSmokeScript(unittest.TestCase):
    def test_without_key_exits_2_and_prints_config(self):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("NEBIUS_API_KEY", "NVIDIA_API_KEY")
        }
        env["NEBIUS_API_KEY"] = ""
        out = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smoke_nvidia.py")],
            capture_output=True,
            text=True,
            env=env,
            cwd=tempfile.mkdtemp(),
            timeout=60,
            check=False,
        )
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("nvidia/nemotron", out.stdout)
        self.assertIn("NOT RUN", out.stdout)

    def test_key_value_is_never_printed(self):
        env = dict(
            os.environ,
            NEBIUS_API_KEY="fake-smoke-key-0003",
            NVIDIA_BASE_URL="http://127.0.0.1:9/v1/",
            AI_TIMEOUT_S="1",
        )
        out = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smoke_nvidia.py")],
            capture_output=True,
            text=True,
            env=env,
            cwd=tempfile.mkdtemp(),
            timeout=60,
            check=False,
        )
        self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
        self.assertNotIn("fake-smoke-key-0003", out.stdout + out.stderr)
        self.assertIn("FALLBACK", out.stdout)


if __name__ == "__main__":
    unittest.main()
