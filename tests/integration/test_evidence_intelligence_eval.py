"""Integration test executing the 5-scenario Evidence Intelligence evaluation benchmark."""

from __future__ import annotations

import unittest

from packages.domain.research_eval import run_evaluation


class TestEvidenceIntelligenceEvaluation(unittest.TestCase):
    def test_run_full_evaluation_benchmark(self):
        report = run_evaluation()
        self.assertEqual(report["total_scenarios"], 5)
        self.assertTrue(
            report["all_safety_invariants_passed"],
            "Safety invariants must be preserved across all research scenarios",
        )
        self.assertTrue(
            report["all_injection_defenses_passed"],
            "Prompt-injection attacks in external search snippets must be neutralized",
        )

        # Inspect specific scenarios
        scenarios = {s["scenario_id"]: s for s in report["scenarios"]}

        # SCEN-01 (Cardiac)
        sc1 = scenarios["SCEN-01"]
        self.assertEqual(sc1["research_status"], "live")
        self.assertIn("redcross.org.uk", sc1["domains"])

        # SCEN-04 (Prompt Injection Defense)
        sc4 = scenarios["SCEN-04"]
        self.assertTrue(sc4["injection_prevented"])
        self.assertTrue(sc4["safety_invariant_preserved"])

        # SCEN-05 (Resilience / 503 outage)
        sc5 = scenarios["SCEN-05"]
        self.assertEqual(sc5["research_status"], "unavailable")
        self.assertEqual(sc5["research_label"], "research unavailable: http 503")
        self.assertEqual(sc5["results_count"], 0)
