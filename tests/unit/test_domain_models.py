"""Unit tests for LifeRescue Unified Domain Models."""

import unittest
from datetime import datetime
from packages.domain.models import (
    AIAnalysis,
    EmergencyContact,
    Incident,
    IncidentStatus,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
    ResponsePlan,
    RiskAssessment,
    UrgencyLevel,
    User,
    generate_id,
)


class TestDomainModels(unittest.TestCase):
    def test_id_generation(self):
        uid = generate_id("inc")
        self.assertTrue(uid.startswith("inc_"))
        self.assertGreater(len(uid), 10)

    def test_user_creation(self):
        user = User(user_id="usr_01", name="Alice", email="alice@test.com")
        self.assertEqual(user.name, "Alice")
        self.assertEqual(user.email, "alice@test.com")
        self.assertIsInstance(user.created_at, datetime)

    def test_emergency_contact_validation(self):
        contact = EmergencyContact(
            user_id="usr_01",
            name="Bob",
            relationship="Brother",
            phone="+1234567890",
            is_primary=True,
        )
        self.assertTrue(contact.is_primary)
        self.assertTrue(contact.notify_on_escalation)

    def test_incident_status_and_urgency(self):
        inc = Incident(
            title="House fire reported",
            description="Smoke visible from roof",
            location="10 Main St",
        )
        self.assertEqual(inc.status, IncidentStatus.OPEN)
        self.assertEqual(inc.urgency, UrgencyLevel.MEDIUM)
        self.assertEqual(inc.input_type, "text")

    def test_ai_analysis_fields(self):
        ana = AIAnalysis(
            incident_id="inc_01",
            summary="Cardiac emergency",
            category="medical",
            urgency=UrgencyLevel.CRITICAL,
            severity_score=9,
            confidence=0.92,
            immediate_threat=True,
            missing_critical_info=["location"],
            recommended_immediate_steps=["Call 911"],
        )
        self.assertEqual(ana.severity_score, 9)
        self.assertTrue(ana.immediate_threat)
        self.assertEqual(ana.category, "medical")

    def test_risk_assessment_disclaimer(self):
        risk = RiskAssessment(
            incident_id="inc_01",
            urgency=UrgencyLevel.CRITICAL,
            requires_escalation=True,
            escalation_reason="Severe chest pain",
        )
        self.assertTrue(risk.requires_escalation)
        self.assertIn("does not replace", risk.medical_disclaimer.lower())

    def test_response_action_and_plan(self):
        action = ResponseAction(
            action_type=ResponseActionType.CALL_EMERGENCY_SERVICES,
            title="Call 911",
            description="Contact dispatcher",
            is_escalation=True,
            mocked=True,
        )
        plan = ResponsePlan(
            incident_id="inc_01",
            rationale="Immediate response required",
            actions=[action],
        )
        self.assertEqual(len(plan.actions), 1)
        self.assertTrue(plan.actions[0].mocked)
        self.assertEqual(plan.actions[0].status, ResponseActionStatus.PENDING)

    def test_strict_model_extra_fields_rejected(self):
        with self.assertRaises(Exception):
            User(
                user_id="u1",
                name="John",
                email="j@test.com",
                unapproved_field="malicious_payload",
            )  # type: ignore


if __name__ == "__main__":
    unittest.main()
