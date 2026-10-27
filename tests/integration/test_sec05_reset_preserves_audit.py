"""LR 08 SEC-05 (High): /demo/reset must not delete audit history; it appends demo_reset."""

import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app


class TestSec05(unittest.TestCase):
    def setUp(self):
        reset_for_tests(":memory:")
        self.client = TestClient(create_app(Settings(db_path=":memory:", ai_provider="mock")))

    def test_reset_keeps_audit_and_appends_event(self):
        r = self.client.post("/demo/scenarios/scenario_medical/run").json()
        iid = r["incident"]["incident_id"]
        before = self.client.get("/audit/events", params={"limit": 500}).json()
        before_ids = {e["event_id"] for e in before}
        self.assertTrue(any(e.get("incident_id") == iid for e in before))

        res = self.client.post("/demo/reset").json()
        self.assertNotIn("audit", res["cleared"])
        after = self.client.get("/audit/events", params={"limit": 500}).json()
        after_ids = {e["event_id"] for e in after}
        self.assertTrue(before_ids <= after_ids, "audit rows were deleted by reset")
        self.assertTrue(any(e["event_type"] == "demo_reset" for e in after))
        self.assertTrue(any(e.get("incident_id") == iid for e in after))


if __name__ == "__main__":
    unittest.main()
