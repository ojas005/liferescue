"""LR 08 SEC-14 (Low): GitHub and sk- tokens are redacted at storage (API level)."""

import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app

GHP = "ghp_" + "A1b2C3d4E5" * 4  # synthetic
PAT = "github_pat_" + "11ABCDEFG0" * 3 + "_xyz"  # synthetic
SK = "sk-" + "Zz9Yy8Xx7W" * 3  # synthetic


class TestSec14Storage(unittest.TestCase):
    def test_stored_incident_redacted(self):
        reset_for_tests(":memory:")
        c = TestClient(create_app(Settings(db_path=":memory:", ai_provider="mock")))
        inc = c.post(
            "/incidents",
            json={
                "title": "x",
                "description": f"keys {GHP} {SK} {PAT}",
                "input_type": "text",
            },
        ).json()
        got = c.get(f"/incidents/{inc['incident_id']}").text
        for tok in (GHP, SK, PAT):
            self.assertNotIn(tok, got)


if __name__ == "__main__":
    unittest.main()
