"""KAN-50: Integration tests for Tavily research workflow across FastAPI endpoints."""

from __future__ import annotations

import json
import unittest

import httpx
from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app
from packages.domain.research import LIVE_LABEL, TavilyResearchTool

MOCK_KEY = "mock-tavily-test-key"

SAMPLE_TAVILY_PAYLOAD = {
    "query": "first aid safety guidance medical emergency critical",
    "results": [
        {
            "title": "AHA Emergency Cardiac Guidelines",
            "url": "https://cpr.heart.org/cardiac-guidance",
            "content": "Call 911 immediately and begin high-quality chest compressions.",
        },
        {
            "title": "Red Cross First Aid Guide",
            "url": "https://www.redcross.org/take-a-class/first-aid",
            "content": "Check surroundings for hazards, verify breathing, deploy AED if available.",
        },
    ],
}


def _mock_tavily_handler(req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=SAMPLE_TAVILY_PAYLOAD)


class TestTavilyIntegration(unittest.TestCase):
    def setUp(self):
        self.mock_tool = TavilyResearchTool(
            api_key=MOCK_KEY,
            transport=httpx.MockTransport(_mock_tavily_handler),
        )
        self.app = create_app(
            Settings(ai_provider="mock", demo_mode=True, tavily_api_key=MOCK_KEY)
        )
        reset_for_tests(":memory:", research_tool=self.mock_tool)
        self.client = TestClient(self.app)

    def test_demo_scenario_executes_tavily_research(self):
        resp = self.client.post("/demo/scenarios/scenario_medical/run")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # 1. Research payload returned in scenario response
        self.assertIn("research", data)
        research = data["research"]
        self.assertIsNotNone(research)
        self.assertEqual(research["status"], "live")
        self.assertEqual(research["label"], LIVE_LABEL)
        self.assertEqual(len(research["results"]), 2)
        self.assertEqual(
            research["results"][0]["title"], "AHA Emergency Cardiac Guidelines"
        )
        self.assertEqual(
            research["results"][0]["url"], "https://cpr.heart.org/cardiac-guidance"
        )
        self.assertIn("Untrusted third-party evidence", research["note"])

        # 2. Timeline includes research_evidence event
        incident_id = data["incident"]["incident_id"]
        timeline_events = data["timeline"]
        research_events = [
            e for e in timeline_events if e["event_type"] == "research_evidence"
        ]
        self.assertEqual(len(research_events), 1)
        rev = research_events[0]
        self.assertEqual(rev["actor"], "tavily_research")
        self.assertEqual(rev["payload"]["status"], "live")

        # 3. Explicit GET /incidents/{id}/timeline returns event
        t_resp = self.client.get(f"/incidents/{incident_id}/timeline")
        self.assertEqual(t_resp.status_code, 200)
        t_data = t_resp.json()
        matching = [
            e for e in t_data["events"] if e["event_type"] == "research_evidence"
        ]
        self.assertEqual(len(matching), 1)

        # 4. Invariant: Secret key is never leaked in the response or timeline
        serialized = json.dumps(data)
        self.assertNotIn(MOCK_KEY, serialized)

    def test_incident_analyze_with_missing_credentials(self):
        # Configure tool without API key
        nokey_tool = TavilyResearchTool(api_key="")
        reset_for_tests(":memory:", research_tool=nokey_tool)
        client = TestClient(create_app(Settings(ai_provider="mock")))

        # Create incident
        create_resp = client.post(
            "/incidents",
            json={
                "title": "Kitchen fire",
                "description": "Stove grease fire spreading to cabinets",
                "location": "Kitchen",
                "user_id": "usr_demo",
            },
        )
        self.assertEqual(create_resp.status_code, 201)
        inc_id = create_resp.json()["incident_id"]

        # Trigger analysis
        analyze_resp = client.post(f"/incidents/{inc_id}/analyze")
        self.assertEqual(analyze_resp.status_code, 200)
        an_data = analyze_resp.json()

        # Research must be cleanly unavailable, without breaking triage
        self.assertIn("research", an_data)
        research = an_data["research"]
        self.assertIsNotNone(research)
        self.assertEqual(research["status"], "unavailable")
        self.assertEqual(
            research["label"], "research unavailable: TAVILY_API_KEY not configured"
        )
        self.assertEqual(research["results"], [])

        # Triage and deterministic safety policy completed normally
        self.assertIn("risk", an_data)
        self.assertIn(an_data["risk"]["urgency"], ["high", "critical", "medium"])


if __name__ == "__main__":
    unittest.main()
