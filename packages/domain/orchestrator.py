"""Response Orchestration & Execution for LifeRescue.

Coordinates the end-to-end incident lifecycle:
1. Incident creation and baseline triage.
2. AI-assisted analysis and risk assessment.
3. Safety policy vetting and response plan structuring.
4. Governed action execution / simulation with full audit trails.
"""

from __future__ import annotations

import logging

from packages.domain.interfaces import (
    AIProvider,
    AuditRepository,
    ContactRepository,
    IncidentRepository,
    NotificationProvider,
    ProfileRepository,
)
from packages.domain.models import (
    AIAnalysis,
    AuditEvent,
    EmergencyProfile,
    Incident,
    IncidentEvent,
    IncidentStatus,
    ReadinessAssessment,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
    ResponsePlan,
    RiskAssessment,
    UrgencyLevel,
    utcnow,
)
from packages.domain.safety_policy import SafetyPolicyEngine

logger = logging.getLogger("liferescue.orchestrator")


class MockNotificationProvider(NotificationProvider):
    """Safe, non-network notification dispatcher for hackathon demos and local runs."""

    def is_mock(self) -> bool:
        return True

    def dispatch_action(
        self,
        action: ResponseAction,
        incident: Incident,
        profile: EmergencyProfile | None = None,
    ) -> tuple[bool, str]:
        """Simulate dispatching notifications and external actions."""
        if action.action_type == ResponseActionType.CALL_EMERGENCY_SERVICES:
            msg = (
                f"[SIMULATED DISPATCH] Contacted Emergency Dispatch (911/112). "
                f"Incident '{incident.title}' reported at '{incident.location or 'GPS pending'}'. "
                f"Category: {action.payload.get('category', 'medical')}."
            )
        elif action.action_type == ResponseActionType.NOTIFY_CONTACT:
            name = action.payload.get("name", "Emergency Contact")
            phone = action.payload.get("phone", "unknown")
            msg = (
                f"[SIMULATED SMS] Priority alert transmitted to {name} ({phone}): "
                f"'LifeRescue Alert: Emergency incident reported. Help is en route.'"
            )
        elif action.action_type == ResponseActionType.PREPARE_SUMMARY:
            msg = "[SIMULATED DOSSIER] Generated encrypted responder summary with user medical profile and incident facts."
        elif action.action_type == ResponseActionType.DISPLAY_INSTRUCTIONS:
            msg = "[SYSTEM] First aid and safety instructions rendered to user display."
        else:
            msg = f"[SIMULATION] Action {action.title} executed successfully in test sandbox."

        return True, msg


class ResponseOrchestrator:
    """Core domain orchestrator uniting Capability A, B, and C."""

    def __init__(
        self,
        incident_repo: IncidentRepository,
        profile_repo: ProfileRepository,
        contact_repo: ContactRepository,
        audit_repo: AuditRepository,
        ai_provider: AIProvider,
        safety_engine: SafetyPolicyEngine | None = None,
        notification_provider: NotificationProvider | None = None,
    ):
        self.incident_repo = incident_repo
        self.profile_repo = profile_repo
        self.contact_repo = contact_repo
        self.audit_repo = audit_repo
        self.ai = ai_provider
        self.safety = safety_engine or SafetyPolicyEngine()
        self.notifications = notification_provider or MockNotificationProvider()

    def create_incident(
        self,
        title: str,
        description: str,
        user_id: str = "usr_demo",
        location: str = "",
        input_type: str = "text",
    ) -> Incident:
        """Create new incident record and initialize audit timeline."""
        incident = Incident(
            user_id=user_id,
            title=title,
            description=description,
            location=location,
            input_type=input_type,  # type: ignore[arg-type]
            status=IncidentStatus.OPEN,
            urgency=UrgencyLevel.MEDIUM,
        )
        self.incident_repo.create(incident)

        # Append timeline event
        self.incident_repo.append_event(
            IncidentEvent(
                incident_id=incident.incident_id,
                seq=1,
                event_type="incident_created",
                actor="user",
                summary=f"Incident '{incident.title}' opened via {input_type} intake",
                payload={"location": location, "input_type": input_type},
            )
        )

        # Record audit event
        self.audit_repo.record(
            AuditEvent(
                event_type="INCIDENT_CREATED",
                actor=user_id,
                incident_id=incident.incident_id,
                action="create_incident",
                result="success",
                reason="User initiated emergency intake",
                details={"title": title, "input_type": input_type},
            )
        )

        return incident

    def analyze_incident(self, incident_id: str) -> tuple[AIAnalysis, RiskAssessment]:
        """Triage incident using AI provider and vet with deterministic safety policy."""
        incident = self.incident_repo.get(incident_id)
        if not incident:
            raise ValueError(f"Incident '{incident_id}' not found")

        incident.status = IncidentStatus.ANALYZING
        self.incident_repo.update(incident)

        profile = self.profile_repo.get(incident.user_id)
        contacts = self.contact_repo.list_for_user(incident.user_id)

        # AI analysis
        analysis = self.ai.analyze_emergency(incident, profile, contacts)
        self.incident_repo.save_analysis(analysis)

        # Deterministic Risk & Escalation assessment
        risk = self.safety.evaluate_risk(incident, analysis)

        # Update incident status & urgency
        incident.urgency = risk.urgency
        incident.status = IncidentStatus.TRIAGED
        self.incident_repo.update(incident)

        # Timeline event
        current_timeline = self.incident_repo.get_timeline(incident_id)
        seq = len(current_timeline) + 1
        self.incident_repo.append_event(
            IncidentEvent(
                incident_id=incident_id,
                seq=seq,
                event_type="ai_analysis_completed",
                actor=self.ai.name(),
                summary=f"Triage: {analysis.category} classified as {risk.urgency.value} urgency (Severity: {analysis.severity_score}/10)",
                payload={
                    "urgency": risk.urgency.value,
                    "severity": analysis.severity_score,
                    "confidence": analysis.confidence,
                    "escalation_required": risk.requires_escalation,
                    "missing_info": analysis.missing_critical_info,
                },
            )
        )

        # Audit event
        self.audit_repo.record(
            AuditEvent(
                event_type="INCIDENT_ANALYZED",
                actor=self.ai.name(),
                incident_id=incident_id,
                action="triage_analysis",
                result="success",
                reason=risk.escalation_reason or "Triage analysis completed",
                details={
                    "urgency": risk.urgency.value,
                    "escalation": risk.requires_escalation,
                    "provider": self.ai.name(),
                },
            )
        )

        return analysis, risk

    def plan_response(self, incident_id: str) -> ResponsePlan:
        """Generate structured response plan vetted by safety policy."""
        incident = self.incident_repo.get(incident_id)
        if not incident:
            raise ValueError(f"Incident '{incident_id}' not found")

        analysis = self.incident_repo.get_analysis(incident_id)
        if not analysis:
            # Auto-analyze if not already done
            analysis, risk = self.analyze_incident(incident_id)
        else:
            risk = self.safety.evaluate_risk(incident, analysis)

        profile = self.profile_repo.get(incident.user_id)
        contacts = self.contact_repo.list_for_user(incident.user_id)

        try:
            raw_plan = self.ai.generate_response_plan(
                incident, analysis, profile, contacts
            )
            plan = self.safety.vet_response_plan(incident, raw_plan, risk, contacts)
        except Exception as exc:
            logger.error(
                "AI response planning failed (%s); generating safety fallback plan", exc
            )
            plan = self.safety.generate_fallback_plan(incident, risk, contacts)

        self.incident_repo.save_plan(plan)

        # Timeline event
        current_timeline = self.incident_repo.get_timeline(incident_id)
        self.incident_repo.append_event(
            IncidentEvent(
                incident_id=incident_id,
                seq=len(current_timeline) + 1,
                event_type="response_plan_generated",
                actor="safety_policy",
                summary=f"Safety policy approved response plan with {len(plan.actions)} coordinated actions",
                payload={
                    "action_count": len(plan.actions),
                    "policy_notes": plan.policy_notes,
                },
            )
        )

        # Audit event
        self.audit_repo.record(
            AuditEvent(
                event_type="PLAN_GENERATED",
                actor="safety_policy",
                incident_id=incident_id,
                action="vet_response_plan",
                result="success",
                details={"action_count": len(plan.actions)},
            )
        )

        return plan

    def execute_response(
        self, incident_id: str, action_ids: list[str] | None = None
    ) -> ResponsePlan:
        """Execute/simulate vetted response actions with full audit records."""
        incident = self.incident_repo.get(incident_id)
        if not incident:
            raise ValueError(f"Incident '{incident_id}' not found")

        plan = self.incident_repo.get_plan(incident_id)
        if not plan:
            plan = self.plan_response(incident_id)

        profile = self.profile_repo.get(incident.user_id)

        for action in plan.actions:
            if action_ids is not None and action.action_id not in action_ids:
                continue
            if action.status not in (ResponseActionStatus.PENDING,):
                continue

            success, msg = self.notifications.dispatch_action(action, incident, profile)
            action.status = (
                ResponseActionStatus.SIMULATED
                if self.notifications.is_mock()
                else ResponseActionStatus.EXECUTED
            )
            action.result_message = msg
            action.executed_at = utcnow()

            # Record timeline event for each action
            current_timeline = self.incident_repo.get_timeline(incident_id)
            self.incident_repo.append_event(
                IncidentEvent(
                    incident_id=incident_id,
                    seq=len(current_timeline) + 1,
                    event_type="action_executed",
                    actor="response_orchestrator",
                    summary=f"Executed: {action.title}",
                    payload={
                        "action_type": action.action_type.value,
                        "status": action.status.value,
                        "mocked": action.mocked,
                        "result": msg,
                    },
                )
            )

            # Record audit event
            self.audit_repo.record(
                AuditEvent(
                    event_type="ACTION_EXECUTED",
                    actor="response_orchestrator",
                    incident_id=incident_id,
                    action=action.action_type.value,
                    result="success" if success else "failed",
                    details={
                        "action_id": action.action_id,
                        "mocked": action.mocked,
                        "result": msg,
                    },
                )
            )

        incident.status = IncidentStatus.RESPONDING
        self.incident_repo.update(incident)
        self.incident_repo.save_plan(plan)
        return plan

    def get_timeline(self, incident_id: str) -> list[IncidentEvent]:
        """Retrieve complete chronological incident timeline."""
        return self.incident_repo.get_timeline(incident_id)

    def assess_user_readiness(self, user_id: str = "usr_demo") -> ReadinessAssessment:
        """Run personal emergency readiness assessment (Capability C)."""
        profile = self.profile_repo.get(user_id)
        if not profile:
            profile = EmergencyProfile(user_id=user_id)
            self.profile_repo.save(profile)

        contacts = self.contact_repo.list_for_user(user_id)
        assessment = self.ai.assess_readiness(profile, contacts)

        self.audit_repo.record(
            AuditEvent(
                event_type="READINESS_ASSESSED",
                actor="system",
                action="assess_readiness",
                result="success",
                details={
                    "user_id": user_id,
                    "score": assessment.score,
                    "status": assessment.status,
                },
            )
        )

        return assessment
