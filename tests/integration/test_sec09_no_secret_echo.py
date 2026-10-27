"""LR 08 SEC-09 (Medium): secrets are not echoed in 404/422 bodies or access logs."""

import io
import logging
import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app

FAKE_KEY = "nvapi-" + "FAKEsec09" * 6  # synthetic, LR 08 repro shape


class TestSec09(unittest.TestCase):
    def setUp(self):
        reset_for_tests(":memory:")
        self.client = TestClient(
            create_app(Settings(db_path=":memory:", ai_provider="mock"))
        )

    def test_404_bodies(self):
        for path in (
            f"/incidents/{FAKE_KEY}",
            f"/incidents/{FAKE_KEY}/analysis",
            f"/incidents/{FAKE_KEY}/timeline",
        ):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 404)
                self.assertNotIn(FAKE_KEY, r.text)
        r = self.client.delete(f"/contacts/{FAKE_KEY}")
        self.assertNotIn(FAKE_KEY, r.text)

    def test_422_does_not_echo_input(self):
        r = self.client.post(
            "/incidents",
            json={
                "title": "x",
                "description": ("A" * 5001) + FAKE_KEY,
                "input_type": "text",
            },
        )
        self.assertEqual(r.status_code, 422)
        self.assertNotIn(FAKE_KEY, r.text)
        self.assertNotIn("AAAAAAAA", r.text)

    def test_uvicorn_access_logger_redacts(self):
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        lg = logging.getLogger("uvicorn.access")
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
        try:
            lg.info(
                '%s - "%s %s HTTP/1.1" %d',
                "127.0.0.1:1",
                "GET",
                f"/incidents/{FAKE_KEY}",
                404,
            )
        finally:
            lg.removeHandler(h)
        self.assertIn("/incidents/", buf.getvalue())
        self.assertNotIn(FAKE_KEY, buf.getvalue())


if __name__ == "__main__":
    unittest.main()
