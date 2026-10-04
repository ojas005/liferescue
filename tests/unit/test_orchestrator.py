"""Unit tests for LifeRescue Response Orchestrator."""

import unittest
from packages.domain.ai import MockAIProvider
from packages.domain.models import (
    EmergencyContact,
    EmergencyProfile,
    IncidentStatus,
    ResponseActionStatus,
    User,
)
from packages.domain.orchestrator import MockNotificationProvider, ResponseOrchestrator
from packages.domain.safety_policy import SafetyPolicyEngine
from packages.storage.sqlite_repo import SQLiteDatabase, create_repositories


class TestResponseOrchestrator(unittest.TestCase):
    def setUp(self):
        self.db = SQLiteDatabase(":memory:")
        (
            self.inc_repo,
            self.user_repo,
            self.profile_repo,
            self.contact_repo,
            self.audit_repo,
        ) = create_repositories(self.db)

        # Seed test user
        self.user_repo.save(
            User(user_id="usr_01", name="Dave", email="dave@example.com")
        )
        self.profile_repo.save(EmergencyProfile(user_id="usr_01", blood_type="A+"))
        self.contact_repo.create(
            EmergencyContact(
                user_id="usr_01",
                name="Eve",
                relationship="Sister",
                phone="+1-555-0999",
                is_primary=True,
            )
        )

        self.orch = ResponseOrchestrator(
            incident_repo=self.inc_repo,
            profile_repo=self.profile_repo,
            contact_repo=self.contact_repo,
            audit_repo=self.audit_repo,
            ai_provider=MockAIProvider(),
            safety_engine=SafetyPolicyEngine(),
            notification_provider=MockNotificationProvider(),
        )

    def test_full_orchestration_cycle(self):
        # 1. Intake
        inc = self.orch.create_incident(
            title="Apartment fire reported",
            description="Flames visible in 2nd floor window and thick black smoke",
            user_id="usr_01",
            location="99 Oak Street",
        )
        self.assertEqual(inc.status, IncidentStatus.OPEN)

        # 2. Triage & Analysis
        analysis, risk = self.orch.analyze_incident(inc.incident_id)
        self.assertEqual(analysis.category, "fire_hazard")
        self.assertTrue(risk.requires_escalation)

        # 3. Plan Response
        plan = self.orch.plan_response(inc.incident_id)
        self.assertTrue(plan.approved_by_policy)
        self.assertGreater(len(plan.actions), 0)

        # 4. Execute / Simulate Actions
        executed_plan = self.orch.execute_response(inc.incident_id)
        for action in executed_plan.actions:
            self.assertEqual(action.status, ResponseActionStatus.SIMULATED)
            self.assertTrue(action.mocked)
            self.assertTrue(action.result_message)

        # 5. Timeline Verification
        timeline = self.orch.get_timeline(inc.incident_id)
        self.assertGreaterEqual(len(timeline), 5)
        event_types = [e.event_type for e in timeline]
        self.assertIn("incident_created", event_types)
        self.assertIn("ai_analysis_completed", event_types)
        self.assertIn("response_plan_generated", event_types)
        self.assertIn("action_executed", event_types)

        # 6. Audit Trail
        audit_events = self.audit_repo.list(incident_id=inc.incident_id)
        self.assertGreaterEqual(len(audit_events), 4)

    def test_orchestrator_raises_on_invalid_incident(self):
        with self.assertRaises(ValueError):
            self.orch.analyze_incident("inc_non_existent")


if __name__ == "__main__":
    unittest.main()
