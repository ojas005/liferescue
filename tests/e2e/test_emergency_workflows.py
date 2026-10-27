"""End-to-End Emergency Workflow Tests for LifeRescue (Section 19 & 20)."""

import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app


class TestEmergencyWorkflowsE2E(unittest.TestCase):
    def setUp(self):
        reset_for_tests(":memory:")
        self.settings = Settings(db_path=":memory:", ai_provider="mock", demo_mode=True)
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

    def test_e2e_scenario_1_medical_emergency(self):
        """Scenario 1: Medical emergency (chest pain and difficulty breathing)."""
        # 1. Intake
        create_res = self.client.post(
            "/incidents",
            json={
                "title": "Severe chest pressure and breathlessness",
                "description": "Crushing chest pain radiating to left jaw, dizziness, struggling to breathe",
                "location": "742 Evergreen Terrace, Springfield",
                "input_type": "text",
            },
        )
        self.assertEqual(create_res.status_code, 201)
        inc_id = create_res.json()["incident_id"]

        # 2. AI Triage & Risk Classification
        triage_res = self.client.post(f"/incidents/{inc_id}/analyze")
        self.assertEqual(triage_res.status_code, 200)
        triage = triage_res.json()
        self.assertEqual(triage["risk"]["urgency"], "critical")
        self.assertTrue(triage["risk"]["requires_escalation"])
        self.assertIn("medical", triage["analysis"]["category"])

        # 3. Response Plan & Simulated Execution
        respond_res = self.client.post(
            f"/incidents/{inc_id}/respond", json={"confirm_all": True}
        )
        self.assertEqual(respond_res.status_code, 200)
        plan = respond_res.json()
        self.assertTrue(plan["approved_by_policy"])

        # Verify 911 dispatch was simulated
        action_types = [a["action_type"] for a in plan["actions"]]
        self.assertIn("call_emergency_services", action_types)
        self.assertIn("notify_contact", action_types)
        self.assertIn("prepare_summary", action_types)
        self.assertIn("display_instructions", action_types)

        # 4. Timeline
        timeline_res = self.client.get(f"/incidents/{inc_id}/timeline")
        self.assertEqual(timeline_res.status_code, 200)
        events = timeline_res.json()["events"]
        self.assertGreaterEqual(len(events), 6)

        # Verify chronological order
        seqs = [e["seq"] for e in events]
        self.assertEqual(seqs, sorted(seqs))

        # 5. Audit Record
        audit_res = self.client.get(f"/audit/events?incident_id={inc_id}")
        self.assertEqual(audit_res.status_code, 200)
        audit_events = audit_res.json()
        self.assertGreaterEqual(len(audit_events), 4)

    def test_e2e_scenario_2_traffic_collision(self):
        """Scenario 2: Traffic accident with injuries."""
        run_res = self.client.post("/demo/scenarios/scenario_accident/run")
        self.assertEqual(run_res.status_code, 200)
        data = run_res.json()
        self.assertEqual(data["analysis"]["category"], "accident")
        self.assertEqual(data["risk"]["urgency"], "high")
        self.assertGreaterEqual(len(data["timeline"]), 5)

    def test_e2e_scenario_3_preparedness_lifecycle(self):
        """Scenario 3: Preparedness assessment and profile remediation."""
        # 1. Start with an empty user
        empty_uid = "usr_new_test"
        readiness_res = self.client.get(f"/readiness?user_id={empty_uid}")
        self.assertEqual(readiness_res.status_code, 200)
        init_data = readiness_res.json()
        self.assertLess(init_data["score"], 50)
        self.assertEqual(init_data["status"], "poor")
        self.assertGreaterEqual(len(init_data["gaps"]), 3)

        # 2. Add emergency contact
        self.client.post(
            f"/contacts?user_id={empty_uid}",
            json={
                "name": "Jane Partner",
                "relationship": "Partner",
                "phone": "+1-555-0987",
                "is_primary": True,
            },
        )

        # 3. Complete emergency profile
        self.client.put(
            f"/emergency-profile?user_id={empty_uid}",
            json={
                "blood_type": "O+",
                "allergies": ["Latex"],
                "medications": ["None"],
                "medical_conditions": ["Asthma"],
                "emergency_instructions": "Contact partner immediately in any trauma event.",
                "primary_language": "en",
                "home_address": "400 Oak Street",
            },
        )

        # 4. Re-evaluate readiness
        updated_res = self.client.get(f"/readiness?user_id={empty_uid}")
        self.assertEqual(updated_res.status_code, 200)
        updated_data = updated_res.json()
        self.assertGreaterEqual(updated_data["score"], 90)
        self.assertEqual(updated_data["status"], "excellent")
        self.assertEqual(len(updated_data["gaps"]), 0)


if __name__ == "__main__":
    unittest.main()
