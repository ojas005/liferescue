"""KAN-50 P1: provider mode is visible in /health, analysis and audit; live output is policy-vetted."""

import json
import unittest

import httpx
from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import get_orchestrator, reset_for_tests
from apps.api.main import create_app
from packages.domain.ai import NVIDIAAIProvider

UNDER_RATED = {
    "summary": "Minor discomfort",
    "category": "medical",
    "urgency": "low",
    "severity_score": 2,
    "confidence": 0.6,
    "immediate_threat": False,
    "extracted_facts": {},
    "missing_critical_info": [],
    "recommended_immediate_steps": ["Rest."],
}


class TestProviderModesAPI(unittest.TestCase):
    def setUp(self):
        reset_for_tests(":memory:")
        settings = Settings(
            db_path=":memory:",
            ai_provider="nebius",
            nebius_api_key=None,
            nvidia_api_key=None,
        )
        self.client = TestClient(create_app(settings))

    def _analyzed_audit(self):
        events = self.client.get("/audit/events").json()
        return [e for e in events if e["event_type"] == "INCIDENT_ANALYZED"]

    def test_no_key_is_labelled_fallback_everywhere(self):
        orch = get_orchestrator()
        orch.ai.api_key = None
        res = self.client.post("/demo/scenarios/scenario_medical/run").json()
        self.assertIn("mock_fallback: not_configured", res["analysis"]["provider_name"])
        health = self.client.get("/health").json()
        self.assertEqual(health["ai_mode"], "fallback")
        self.assertTrue(health["ai_model"].startswith("nvidia/nemotron"))
        self.assertTrue(self._analyzed_audit()[-1]["details"]["fallback"])
        self.assertTrue(all(a["status"] == "simulated" for a in res["plan"]["actions"]))

    def test_live_provider_output_passes_safety_policy_before_actions(self):
        def handler(request):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(UNDER_RATED)}}]},
            )

        orch = get_orchestrator()
        orch.ai = NVIDIAAIProvider(
            api_key="fake-test-key-0002", transport=httpx.MockTransport(handler)
        )
        res = self.client.post("/demo/scenarios/scenario_medical/run").json()
        self.assertNotIn("mock_fallback", res["analysis"]["provider_name"])
        self.assertEqual(res["analysis"]["urgency"], "low")
        # deterministic policy overrides the under-rated model output
        self.assertTrue(res["risk"]["requires_escalation"])
        self.assertEqual(
            res["risk"]["policy_rule_triggered"], "RULE_ACUTE_LIFE_THREAT_ESCALATION"
        )
        self.assertTrue(res["plan"]["approved_by_policy"])
        self.assertTrue(
            all(
                a["status"] == "simulated" and a["mocked"]
                for a in res["plan"]["actions"]
            )
        )
        self.assertEqual(self.client.get("/health").json()["ai_mode"], "live")
        self.assertFalse(self._analyzed_audit()[-1]["details"]["fallback"])

    def test_long_fallback_label_does_not_break_scenario_run(self):
        """Regression: 'nvidia_ai (mock_fallback: invalid_response:JSONDecodeError)' exceeded the
        50-char IncidentEvent.actor limit and turned a labelled fallback into HTTP 500."""

        def handler(request):
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "not json {"}}]}
            )

        orch = get_orchestrator()
        orch.ai = NVIDIAAIProvider(
            api_key="fake-test-key-0003", transport=httpx.MockTransport(handler)
        )
        for sid in ("scenario_medical", "scenario_accident", "scenario_preparedness"):
            r = self.client.post(f"/demo/scenarios/{sid}/run")
            self.assertEqual(r.status_code, 200, sid)
            res = r.json()
            self.assertIn(
                "mock_fallback: invalid_response", res["analysis"]["provider_name"]
            )
            self.assertTrue(
                all(a["status"] == "simulated" for a in res["plan"]["actions"])
            )
            actors = {e["actor"] for e in res["timeline"]}
            self.assertTrue(any("mock_fallback" in a for a in actors))
            self.assertTrue(all(len(a) <= 50 for a in actors))
        self.assertEqual(self.client.get("/health").json()["ai_mode"], "fallback")
        self.assertTrue(self._analyzed_audit()[-1]["details"]["fallback"])


if __name__ == "__main__":
    unittest.main()
