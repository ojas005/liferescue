"""Integration tests for all LifeRescue REST API endpoints."""

import unittest
from fastapi.testclient import TestClient
from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app


class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        reset_for_tests(":memory:")
        self.settings = Settings(db_path=":memory:", ai_provider="mock", demo_mode=True)
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

    def test_health_check(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["ai_provider"], "mock")
        self.assertTrue(data["demo_mode"])

    def test_web_ui_serving(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("LifeRescue", res.text)
        self.assertIn("text/html", res.headers.get("content-type", ""))

    def test_headers_and_request_id(self):
        res = self.client.get("/health")
        self.assertIn("X-Request-ID", res.headers)
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")

    def test_incident_lifecycle_flow(self):
        # 1. Create incident
        res = self.client.post(
            "/incidents",
            json={
                "title": "Severe shortness of breath",
                "description": "Difficulty inhaling and cyanosis around lips",
                "location": "Central Park East",
                "input_type": "text",
            },
        )
        self.assertEqual(res.status_code, 201)
        inc = res.json()
        inc_id = inc["incident_id"]

        # 2. Get incident by ID
        res = self.client.get(f"/incidents/{inc_id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["incident_id"], inc_id)

        # 3. Analyze incident
        res = self.client.post(f"/incidents/{inc_id}/analyze")
        self.assertEqual(res.status_code, 200)
        triage = res.json()
        self.assertEqual(triage["risk"]["urgency"], "critical")
        self.assertTrue(triage["risk"]["requires_escalation"])

        # 4. Get Analysis
        res = self.client.get(f"/incidents/{inc_id}/analysis")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["category"], "medical")

        # 5. Respond to incident
        res = self.client.post(
            f"/incidents/{inc_id}/respond", json={"confirm_all": True}
        )
        self.assertEqual(res.status_code, 200)
        plan = res.json()
        self.assertTrue(plan["approved_by_policy"])
        self.assertGreater(len(plan["actions"]), 0)

        # 6. Timeline
        res = self.client.get(f"/incidents/{inc_id}/timeline")
        self.assertEqual(res.status_code, 200)
        events = res.json()["events"]
        self.assertGreaterEqual(len(events), 4)

    def test_emergency_profile_and_readiness(self):
        # Get default seeded profile
        res = self.client.get("/emergency-profile?user_id=usr_demo")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["blood_type"], "O+")

        # Update profile
        res = self.client.put(
            "/emergency-profile?user_id=usr_demo",
            json={
                "blood_type": "AB+",
                "allergies": ["Latex"],
                "medications": ["Aspirin"],
                "medical_conditions": ["Hypertension"],
                "emergency_instructions": "Spare key under planter box.",
                "primary_language": "en",
                "home_address": "123 Broadway, NY",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["blood_type"], "AB+")

        # Readiness evaluation
        res = self.client.get("/readiness?user_id=usr_demo")
        self.assertEqual(res.status_code, 200)
        readiness = res.json()
        self.assertGreaterEqual(readiness["score"], 80)
        self.assertEqual(readiness["status"], "excellent")

    def test_contacts_crud(self):
        # Create contact
        res = self.client.post(
            "/contacts?user_id=usr_demo",
            json={
                "name": "Emergency Aunt",
                "relationship": "Aunt",
                "phone": "+1-555-4321",
                "is_primary": False,
            },
        )
        self.assertEqual(res.status_code, 201)
        cnt_id = res.json()["contact_id"]

        # List contacts
        res = self.client.get("/contacts?user_id=usr_demo")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(any(c["contact_id"] == cnt_id for c in res.json()))

        # Update contact
        res = self.client.put(f"/contacts/{cnt_id}", json={"phone": "+1-555-9999"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["phone"], "+1-555-9999")

        # Delete contact
        res = self.client.delete(f"/contacts/{cnt_id}")
        self.assertEqual(res.status_code, 204)

    def test_demo_scenarios(self):
        res = self.client.get("/demo/scenarios")
        self.assertEqual(res.status_code, 200)
        scenarios = res.json()
        self.assertEqual(len(scenarios), 3)

        # Run Scenario 1 (Medical)
        res = self.client.post("/demo/scenarios/scenario_medical/run")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["risk"]["urgency"], "critical")
        self.assertTrue(data["risk"]["requires_escalation"])
        self.assertGreaterEqual(len(data["timeline"]), 5)

        # Run Scenario 2 (Accident)
        res = self.client.post("/demo/scenarios/scenario_accident/run")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["analysis"]["category"], "accident")

    def test_audit_events_endpoint(self):
        # Generate an incident to populate audit logs
        self.client.post("/demo/scenarios/scenario_medical/run")
        res = self.client.get("/audit/events")
        self.assertEqual(res.status_code, 200)
        logs = res.json()
        self.assertGreater(len(logs), 0)


if __name__ == "__main__":
    unittest.main()
