"""LR 08 SEC-08 (Medium): requires_confirmation is enforced; unknown action ids rejected."""

import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import get_orchestrator, reset_for_tests
from apps.api.main import create_app


class TestSec08(unittest.TestCase):
    def setUp(self):
        reset_for_tests(":memory:")
        self.client = TestClient(
            create_app(Settings(db_path=":memory:", ai_provider="mock"))
        )
        inc = self.client.post(
            "/incidents",
            json={
                "title": "x",
                "description": "My father has chest pain",
                "input_type": "text",
            },
        ).json()
        self.iid = inc["incident_id"]
        self.client.post(f"/incidents/{self.iid}/analyze")
        orch = get_orchestrator()
        plan = orch.plan_response(self.iid)
        self.gated = plan.actions[-1]
        self.gated.requires_confirmation = True
        orch.incident_repo.save_plan(plan)

    def _status(self, plan, aid):
        return next(a["status"] for a in plan["actions"] if a["action_id"] == aid)

    def test_gated_action_skipped_without_approval_then_runs_when_approved(self):
        plan = self.client.post(f"/incidents/{self.iid}/respond", json={}).json()
        self.assertEqual(self._status(plan, self.gated.action_id), "pending")
        others = [a for a in plan["actions"] if a["action_id"] != self.gated.action_id]
        self.assertTrue(all(a["status"] == "simulated" for a in others))
        audit = self.client.get(
            "/audit/events", params={"incident_id": self.iid, "limit": 500}
        ).json()
        self.assertTrue(
            any(e["event_type"] == "ACTION_AWAITING_CONFIRMATION" for e in audit)
        )

        plan = self.client.post(
            f"/incidents/{self.iid}/respond",
            json={"action_ids": [self.gated.action_id]},
        ).json()
        self.assertEqual(self._status(plan, self.gated.action_id), "simulated")
        audit = self.client.get(
            "/audit/events", params={"incident_id": self.iid, "limit": 500}
        ).json()
        self.assertTrue(
            any(
                e["event_type"] == "APPROVAL"
                and e["details"]["action_id"] == self.gated.action_id
                for e in audit
            )
        )

    def test_unknown_action_id_rejected(self):
        r = self.client.post(
            f"/incidents/{self.iid}/respond",
            json={"action_ids": ["act_does_not_exist"]},
        )
        self.assertEqual(r.status_code, 400)

    def test_respond_404_does_not_echo_id(self):
        r = self.client.post("/incidents/nvapi-ECHOCHECK1234567890/respond", json={})
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("ECHOCHECK", r.text)


if __name__ == "__main__":
    unittest.main()
