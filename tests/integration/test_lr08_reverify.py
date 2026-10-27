"""LR 08 re-verify N-01 (recall gaps)."""

import unittest

from fastapi.testclient import TestClient

from apps.api.config import Settings
from apps.api.dependencies import reset_for_tests
from apps.api.main import create_app

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
            create_app(Settings(db_path=":memory:", ai_provider="mock"))
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


if __name__ == "__main__":
    unittest.main()
