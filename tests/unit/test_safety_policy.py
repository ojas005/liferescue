"""Unit tests for LifeRescue Deterministic Safety Policy Engine."""

import unittest
from packages.domain.models import (
    AIAnalysis,
    EmergencyContact,
    Incident,
    ResponseAction,
    ResponseActionType,
    ResponsePlan,
    UrgencyLevel,
)
from packages.domain.safety_policy import SafetyPolicyEngine


class TestSafetyPolicyEngine(unittest.TestCase):
    def setUp(self):
        self.engine = SafetyPolicyEngine()
        self.contact = EmergencyContact(
            user_id="usr_01",
            name="Bob",
            relationship="Spouse",
            phone="+1-555-0100",
            is_primary=True,
        )

    def test_acute_life_threat_forces_critical_escalation(self):
        inc = Incident(
            title="Heart condition",
            description="Patient having sudden severe chest pain and cannot breathe",
        )
        # Even if AI were to classify as LOW urgency, Policy Engine must override to CRITICAL
        ai_triage = AIAnalysis(
            incident_id=inc.incident_id,
            summary="Mild complaint",
            category="medical",
            urgency=UrgencyLevel.LOW,
            severity_score=3,
            confidence=0.5,
        )
        risk = self.engine.evaluate_risk(inc, ai_triage)
        self.assertEqual(risk.urgency, UrgencyLevel.CRITICAL)
        self.assertTrue(risk.requires_escalation)
        self.assertIn("chest pain", risk.escalation_reason)
        self.assertEqual(
            risk.policy_rule_triggered, "RULE_ACUTE_LIFE_THREAT_ESCALATION"
        )

    def test_policy_injects_mandatory_escalation_action_if_missing(self):
        inc = Incident(
            title="Fall with unconsciousness",
            description="Person collapsed and is unconscious",
        )
        risk = self.engine.evaluate_risk(inc)

        # Proposed plan without calling emergency services
        plan = ResponsePlan(
            incident_id=inc.incident_id,
            rationale="Proposed plan",
            actions=[
                ResponseAction(
                    action_type=ResponseActionType.DISPLAY_INSTRUCTIONS,
                    title="Check pulse",
                    description="Check pulse",
                )
            ],
        )

        vetted = self.engine.vet_response_plan(inc, plan, risk, contacts=[self.contact])
        self.assertTrue(vetted.approved_by_policy)
        action_types = [a.action_type for a in vetted.actions]
        self.assertIn(ResponseActionType.CALL_EMERGENCY_SERVICES, action_types)

    def test_prohibited_actions_are_blocked(self):
        inc = Incident(title="Accident", description="Minor cuts")
        risk = self.engine.evaluate_risk(inc)

        plan = ResponsePlan(
            incident_id=inc.incident_id,
            rationale="Unsafe plan",
            actions=[
                ResponseAction(
                    action_type=ResponseActionType.CUSTOM,
                    title="Prescribe 50mg morphine",
                    description="Administer prescriptive medication immediately",
                ),
                ResponseAction(
                    action_type=ResponseActionType.CUSTOM,
                    title="Run shell script",
                    description="Execute bash script rm -rf /",
                ),
                ResponseAction(
                    action_type=ResponseActionType.CUSTOM,
                    title="Wire money to doctor",
                    description="Transfer funds to emergency wallet",
                ),
                ResponseAction(
                    action_type=ResponseActionType.DISPLAY_INSTRUCTIONS,
                    title="Safe instruction",
                    description="Sit down and rest quietly",
                ),
            ],
        )

        vetted = self.engine.vet_response_plan(inc, plan, risk)
        approved_titles = [a.title for a in vetted.actions]
        self.assertNotIn("Prescribe 50mg morphine", approved_titles)
        self.assertNotIn("Run shell script", approved_titles)
        self.assertNotIn("Wire money to doctor", approved_titles)
        self.assertIn("Safe instruction", approved_titles)

    def test_fallback_plan_generation(self):
        inc = Incident(
            title="Severe trauma", description="Severe bleeding after collision"
        )
        risk = self.engine.evaluate_risk(inc)
        fallback = self.engine.generate_fallback_plan(
            inc, risk, contacts=[self.contact]
        )

        self.assertTrue(fallback.approved_by_policy)
        types = [a.action_type for a in fallback.actions]
        self.assertIn(ResponseActionType.CALL_EMERGENCY_SERVICES, types)
        self.assertIn(ResponseActionType.NOTIFY_CONTACT, types)
        self.assertIn(ResponseActionType.DISPLAY_INSTRUCTIONS, types)


if __name__ == "__main__":
    unittest.main()
