"""LR 08 SEC-01 (Critical): deterministic life-threat recall. Table-driven, through the real API."""

import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app

CRITICAL_CASES = [
    "She took an overdose of pills and is having a seizure",  # LR 08 repro
    "Child drowning in pool, not responding",  # LR 08 repro
    "I want to kill myself tonight",  # LR 08 repro
    "not breathing and turning blue",  # LR 08 repro (was only OK by mock substring)
    "My husband is not breathing and won\u2019t wake up",  # curly apostrophe
    "my dad is unconscious on the floor",
    "my toddler is choking on a grape",
    "he is bleeding heavily from his leg",
    "her face is drooping and she has slurred speech",
    "my friend is having convulsions",
    "kid swallowed bleach",
    "I have been self-harming and cut my wrists",
    "my brother was stabbed",
    "wildfire flames 200m from our house, evacuation order issued",
]


class TestSec01Recall(unittest.TestCase):
    def setUp(self):
        reset_for_tests(":memory:")
        self.client = TestClient(create_app(Settings(db_path=":memory:", ai_provider="mock")))

    def _run(self, text):
        inc = self.client.post("/incidents", json={"title": "Help", "description": text, "input_type": "text"}).json()
        tri = self.client.post(f"/incidents/{inc['incident_id']}/analyze").json()
        plan = self.client.post(f"/incidents/{inc['incident_id']}/respond", json={}).json()
        return tri, plan

    def test_life_threats_are_critical_with_simulated_emergency_call(self):
        for text in CRITICAL_CASES:
            with self.subTest(text=text):
                tri, plan = self._run(text)
                self.assertEqual(tri["risk"]["urgency"], "critical")
                self.assertTrue(tri["risk"]["requires_escalation"])
                self.assertTrue(tri["risk"]["conditions"])
                calls = [a for a in plan["actions"] if a["action_type"] == "call_emergency_services"]
                self.assertTrue(calls, plan["actions"])
                self.assertTrue(all(a["mocked"] for a in plan["actions"]))

    def test_suicidal_intent_adds_crisis_line(self):
        _, plan = self._run("I want to kill myself tonight")
        crisis = [a for a in plan["actions"] if a.get("payload", {}).get("resource") == "crisis_line"]
        self.assertEqual(len(crisis), 1)
        self.assertIn("988", crisis[0]["description"])

    def test_benign_text_not_escalated(self):
        tri, _ = self._run("I scraped my knee on the sidewalk")
        self.assertNotEqual(tri["risk"]["urgency"], "critical")
        self.assertEqual(tri["risk"]["conditions"], [])


if __name__ == "__main__":
    unittest.main()
