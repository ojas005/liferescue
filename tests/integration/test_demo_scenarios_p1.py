"""KAN-50 P1 (d, e): demo response carries persisted urgency; wildfire gets wildfire guidance."""

import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app


class TestDemoScenariosP1(unittest.TestCase):
    def setUp(self):
        reset_for_tests(":memory:")
        self.client = TestClient(
            create_app(Settings(db_path=":memory:", ai_provider="mock"))
        )

    def test_incident_urgency_matches_risk(self):
        for sid in ("scenario_medical", "scenario_accident", "scenario_preparedness"):
            with self.subTest(sid=sid):
                r = self.client.post(f"/demo/scenarios/{sid}/run").json()
                self.assertEqual(r["incident"]["urgency"], r["risk"]["urgency"])
                stored = self.client.get(
                    f"/incidents/{r['incident']['incident_id']}"
                ).json()
                self.assertEqual(stored["urgency"], r["risk"]["urgency"])

    def test_wildfire_steps_are_wildfire_specific(self):
        r = self.client.post("/demo/scenarios/scenario_preparedness/run").json()
        self.assertIn("wildfire", r["risk"]["conditions"])
        steps = " ".join(r["analysis"]["recommended_immediate_steps"]).lower()
        for want in ("evacuation", "go-bag", "smoke"):
            self.assertIn(want, steps)
        self.assertNotIn("elevator", steps)
        disp = [
            a
            for a in r["plan"]["actions"]
            if a["action_type"] == "display_instructions"
        ]
        self.assertNotIn("elevator", disp[0]["description"].lower())
        self.assertEqual(
            r["risk"]["policy_rule_triggered"], "RULE_ACUTE_LIFE_THREAT_ESCALATION"
        )


if __name__ == "__main__":
    unittest.main()
