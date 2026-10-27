"""LR 08 re-verify N-01 (recall gaps) and N-02 (MEDIUM floor + always a call-for-help step)."""

import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app
from packages.domain.models import AIAnalysis, Incident, UrgencyLevel
from packages.domain.safety_policy import SafetyPolicyEngine
from packages.domain.triage_rules import GENERIC_DANGER_STEP, vetted_steps

N01_CASES = [  # LR 08 re-verify exact inputs
    "He OD'd on pills",
    "brother is hanging in the garage",
    "baby is limp and blue",
    "swallowed a whole bottle of sleeping tablets",
    "jumped off the roof and isn't moving",
    "going to end it all tonight",
]


class TestLR08ReverifyN01(unittest.TestCase):
    def setUp(self):
        reset_for_tests(":memory:")
        self.client = TestClient(
            create_app(
                Settings(db_path=":memory:", ai_provider="mock", rate_limit_requests=0)
            )  # recall corpus exceeds the per-IP demo limit
        )

    def _run(self, text):
        inc = self.client.post(
            "/incidents",
            json={"title": "Help", "description": text, "input_type": "text"},
        ).json()
        tri = self.client.post(f"/incidents/{inc['incident_id']}/analyze").json()
        plan = self.client.post(
            f"/incidents/{inc['incident_id']}/respond", json={}
        ).json()
        return tri, plan

    def test_n01_recall_gaps_are_critical_with_emergency_call(self):
        for text in N01_CASES:
            with self.subTest(text=text):
                tri, plan = self._run(text)
                self.assertEqual(tri["risk"]["urgency"], "critical")
                self.assertTrue(tri["risk"]["requires_escalation"])
                types = [a["action_type"] for a in plan["actions"]]
                self.assertIn("call_emergency_services", types)
                self.assertTrue(all(a["mocked"] for a in plan["actions"]))

    def test_n01_end_it_all_adds_crisis_line(self):
        _, plan = self._run("going to end it all tonight")
        crisis = [
            a
            for a in plan["actions"]
            if a.get("payload", {}).get("resource") == "crisis_line"
        ]
        self.assertEqual(len(crisis), 1)
        self.assertIn("988", crisis[0]["description"])


class TestLR08ReverifyN02(unittest.TestCase):
    def test_n02_model_low_is_floored_to_medium(self):
        inc = Incident(title="Question", description="I have a small paper cut")
        ana = AIAnalysis(
            incident_id=inc.incident_id,
            summary="minor",
            category="medical",
            urgency=UrgencyLevel.LOW,
            severity_score=1,
            confidence=0.9,
        )
        risk = SafetyPolicyEngine().evaluate_risk(inc, ana)
        self.assertEqual(risk.urgency, UrgencyLevel.MEDIUM)

    def test_n02_call_for_help_step_always_present(self):
        for cat in ("medical", "accident", "fire_hazard", "other"):
            with self.subTest(category=cat):
                steps = vetted_steps([], cat, escalate=False)
                self.assertEqual(steps[0], GENERIC_DANGER_STEP)
                self.assertIn("112 / 911", steps[0])


R01_CASES = [  # LR 08 reverify-2 R-01 exact inputs (incl. Hindi/Hinglish)
    "he hung himself",
    "found him hanging",
    "slit her wrists",
    "i wanna die",
    "kms",
    "took like 30 xanax",
    "she is unconcious",
    "fell from 3rd floor",
    "hit by truck",
    "saans nahi le rahe",
    "zeher kha liya",
    "behosh",
    "marna chahta hoon",
]
R01_SELF_HARM = {
    "he hung himself",
    "found him hanging",
    "slit her wrists",
    "i wanna die",
    "kms",
    "marna chahta hoon",
}


class TestLR08ReverifyR01(TestLR08ReverifyN01):
    def test_r01_recall_is_critical_with_emergency_call_and_crisis_line(self):
        for text in R01_CASES:
            with self.subTest(text=text):
                tri, plan = self._run(text)
                self.assertEqual(tri["risk"]["urgency"], "critical")
                types = [a["action_type"] for a in plan["actions"]]
                self.assertIn("call_emergency_services", types)
                crisis = [
                    a
                    for a in plan["actions"]
                    if a.get("payload", {}).get("resource") == "crisis_line"
                ]
                if text in R01_SELF_HARM:
                    self.assertEqual(len(crisis), 1)
                    self.assertIn("988", crisis[0]["description"])
                    self.assertIn("Tele-MANAS 14416", crisis[0]["description"])

    def test_r01_benign_inputs_not_flagged(self):
        from packages.domain.triage_rules import detect_conditions

        for text in ("I took 2 tablets for headache", "the car hit a pole lightly"):
            with self.subTest(text=text):
                self.assertEqual(detect_conditions(text), [])


if __name__ == "__main__":
    unittest.main()
