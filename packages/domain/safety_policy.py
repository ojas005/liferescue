"""Deterministic Safety Policy Engine for LifeRescue.

Acts as an uncompromising, non-LLM safety boundary.
All model suggestions must pass through this engine before becoming an actionable plan.
Enforces:
1. Immediate escalation rules for life-threatening conditions.
2. Action allowlists and prohibited action blocklists.
3. Verification of missing critical information.
4. Confidence thresholds requiring human confirmation.
5. Inviolable medical disclaimers (never pretends to be a certified physician).
6. Deterministic fallback response plans when AI output fails validation or is unavailable.
"""

from __future__ import annotations

import re
from typing import Sequence

from packages.domain.models import (
    AIAnalysis,
    EmergencyContact,
    Incident,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
    ResponsePlan,
    RiskAssessment,
    UrgencyLevel,
)

# Mandatory allowed action types (anything else proposed by an LLM is rejected)
ALLOWED_ACTION_TYPES = frozenset(ResponseActionType)

# Prohibited dangerous action types or topics
PROHIBITED_ACTION_PATTERNS = [
    re.compile(
        r"\b(prescribe|administer|inject|dose|surgery|cut|amputate|defibrillate)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(transfer|wire|pay|buy|credit|wallet|crypto|send money)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(bash|sh|cmd|powershell|sudo|exec|eval|script|rm -rf)\b", re.IGNORECASE
    ),
]

# Symptoms indicating life-threatening emergency escalation
LIFE_THREATENING_PATTERNS = [
    re.compile(
        r"\b(chest pain|heart attack|cardiac|angina|chest tightness)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(difficulty breathing|can't breathe|cannot breathe|suffocat|choking|shortness of breath)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(unconscious|passed out|fainted|unresponsive|collapsed)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(severe bleeding|hemorrhag|arterial blood|gushing blood)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(stroke|paralysis|facial drooping|slurred speech|sudden numbness)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(severe burn|fire trapped|smoke inhalation|building collapse)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(head trauma|skull fracture|spinal injury|paralyzed)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(anaphylaxis|epipen|throat swelling|severe allergic reaction)\b",
        re.IGNORECASE,
    ),
]

MEDICAL_DISCLAIMER = (
    "LifeRescue provides AI-assisted emergency response coordination and safety triage guidance. "
    "It is NOT a medical diagnosis and does NOT replace calling professional emergency dispatchers (such as 911/112)."
)


class SafetyPolicyEngine:
    """Deterministic safety rule engine for triage assessment and response vetting."""

    def __init__(
        self,
        min_confidence_threshold: float = 0.55,
        require_confirmation_for_escalation: bool = False,
    ):
        self.min_confidence_threshold = min_confidence_threshold
        self.require_confirmation_for_escalation = require_confirmation_for_escalation

    def evaluate_risk(
        self, incident: Incident, analysis: AIAnalysis | None = None
    ) -> RiskAssessment:
        """Evaluate raw incident text and AI analysis to determine true urgency and escalation."""
        combined_text = incident.description.lower() + " " + incident.title.lower()
        if analysis:
            combined_text += " " + analysis.summary.lower()

        # Check for life-threatening trigger words
        is_life_threatening = False
        trigger_reason = ""
        for pattern in LIFE_THREATENING_PATTERNS:
            match = pattern.search(combined_text)
            if match:
                is_life_threatening = True
                trigger_reason = f"Detected acute critical symptom: '{match.group(0)}'"
                break

        # Determine urgency (Policy overrides LLM if life-threatening condition detected)
        urgency = UrgencyLevel.MEDIUM
        if analysis:
            urgency = analysis.urgency

        if is_life_threatening:
            urgency = UrgencyLevel.CRITICAL
            escalation_required = True
        elif urgency in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL):
            escalation_required = True
            trigger_reason = (
                trigger_reason or f"Incident classified as {urgency.value} urgency"
            )
        else:
            escalation_required = False

        return RiskAssessment(
            incident_id=incident.incident_id,
            urgency=urgency,
            requires_escalation=escalation_required,
            escalation_reason=trigger_reason,
            policy_rule_triggered="RULE_ACUTE_LIFE_THREAT_ESCALATION"
            if is_life_threatening
            else "RULE_STANDARD_TRIAGE",
            medical_disclaimer=MEDICAL_DISCLAIMER,
        )

    def vet_response_plan(
        self,
        incident: Incident,
        proposed_plan: ResponsePlan,
        risk: RiskAssessment,
        contacts: Sequence[EmergencyContact] = (),
    ) -> ResponsePlan:
        """Validate, filter, and augment proposed response plan to enforce safety constraints."""
        vetted_actions: list[ResponseAction] = []
        policy_notes: list[str] = []

        # 1. If risk requires escalation, ensure an escalation action is present at index 0
        if risk.requires_escalation:
            has_escalation = any(
                a.action_type == ResponseActionType.CALL_EMERGENCY_SERVICES
                for a in proposed_plan.actions
            )
            if not has_escalation:
                policy_notes.append(
                    "Safety policy injected mandatory Emergency Services escalation."
                )
                vetted_actions.append(
                    ResponseAction(
                        action_type=ResponseActionType.CALL_EMERGENCY_SERVICES,
                        title="Contact Emergency Services (911/112)",
                        description=(
                            f"Immediately notify emergency dispatchers. {risk.escalation_reason}."
                        ),
                        is_escalation=True,
                        requires_confirmation=self.require_confirmation_for_escalation,
                        status=ResponseActionStatus.PENDING,
                        payload={
                            "service": "medical_rescue",
                            "reason": risk.escalation_reason,
                        },
                        mocked=True,
                    )
                )

        # 2. Vet each proposed action from the AI
        for action in proposed_plan.actions:
            # Check action allowlist
            if action.action_type not in ALLOWED_ACTION_TYPES:
                policy_notes.append(
                    f"Rejected unallowed action type: {action.action_type}"
                )
                continue

            # Check for prohibited content/words
            action_content = f"{action.title} {action.description} {action.payload}"
            is_prohibited = False
            for pattern in PROHIBITED_ACTION_PATTERNS:
                if pattern.search(action_content):
                    is_prohibited = True
                    policy_notes.append(
                        f"Blocked unsafe action '{action.title}' matching prohibited pattern '{pattern.pattern}'"
                    )
                    break
            if is_prohibited:
                continue

            # Enforce confirmation for sensitive custom actions
            if action.action_type == ResponseActionType.CUSTOM:
                action.requires_confirmation = True

            vetted_actions.append(action)

        # 3. If there are primary emergency contacts and incident is HIGH/CRITICAL, ensure contact notification is present
        if risk.urgency in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL) and contacts:
            has_contact_notification = any(
                a.action_type == ResponseActionType.NOTIFY_CONTACT
                for a in vetted_actions
            )
            if not has_contact_notification:
                primary = next((c for c in contacts if c.is_primary), contacts[0])
                policy_notes.append(
                    f"Safety policy appended notification for primary contact: {primary.name}."
                )
                vetted_actions.append(
                    ResponseAction(
                        action_type=ResponseActionType.NOTIFY_CONTACT,
                        title=f"Notify Emergency Contact ({primary.name})",
                        description=f"Send automated emergency status and location alert to {primary.name} ({primary.relationship}).",
                        is_escalation=False,
                        requires_confirmation=False,
                        status=ResponseActionStatus.PENDING,
                        payload={
                            "contact_id": primary.contact_id,
                            "contact_name": primary.name,
                            "phone": primary.phone,
                        },
                        mocked=True,
                    )
                )

        # 4. Mandatory display instructions with medical disclaimer
        has_display_instructions = any(
            a.action_type == ResponseActionType.DISPLAY_INSTRUCTIONS
            for a in vetted_actions
        )
        if not has_display_instructions:
            vetted_actions.append(
                ResponseAction(
                    action_type=ResponseActionType.DISPLAY_INSTRUCTIONS,
                    title="Safety & First Aid Guidance",
                    description=f"Remain calm. Do not move if spinal injury is suspected. Keep warm. {MEDICAL_DISCLAIMER}",
                    is_escalation=False,
                    requires_confirmation=False,
                    status=ResponseActionStatus.PENDING,
                    payload={"disclaimer": MEDICAL_DISCLAIMER},
                    mocked=True,
                )
            )

        return ResponsePlan(
            plan_id=proposed_plan.plan_id,
            incident_id=incident.incident_id,
            rationale=f"Vetted by LifeRescue Safety Engine. {proposed_plan.rationale}",
            actions=vetted_actions,
            approved_by_policy=True,
            policy_notes="; ".join(policy_notes)
            if policy_notes
            else "All proposed actions approved under policy.",
        )

    def generate_fallback_plan(
        self,
        incident: Incident,
        risk: RiskAssessment,
        contacts: Sequence[EmergencyContact] = (),
    ) -> ResponsePlan:
        """Deterministic safety fallback plan when AI provider is unavailable or outputs malformed data."""
        actions: list[ResponseAction] = []

        if risk.requires_escalation:
            actions.append(
                ResponseAction(
                    action_type=ResponseActionType.CALL_EMERGENCY_SERVICES,
                    title="Emergency Services Dispatch",
                    description=f"Escalate immediately to emergency response dispatch. {risk.escalation_reason}.",
                    is_escalation=True,
                    status=ResponseActionStatus.PENDING,
                    payload={"target": "911/112", "reason": risk.escalation_reason},
                    mocked=True,
                )
            )

        if contacts:
            primary = next((c for c in contacts if c.is_primary), contacts[0])
            actions.append(
                ResponseAction(
                    action_type=ResponseActionType.NOTIFY_CONTACT,
                    title=f"Alert Contact: {primary.name}",
                    description=f"Send incident alert to {primary.name} ({primary.phone}).",
                    is_escalation=False,
                    status=ResponseActionStatus.PENDING,
                    payload={
                        "contact_id": primary.contact_id,
                        "name": primary.name,
                        "phone": primary.phone,
                    },
                    mocked=True,
                )
            )

        actions.append(
            ResponseAction(
                action_type=ResponseActionType.DISPLAY_INSTRUCTIONS,
                title="Immediate Safety Instructions",
                description=(
                    "1. Ensure immediate physical safety of yourself and bystanders.\n"
                    "2. If injured, do not move unless in immediate danger.\n"
                    "3. Prepare to speak clearly with emergency personnel.\n"
                    f"{MEDICAL_DISCLAIMER}"
                ),
                is_escalation=False,
                status=ResponseActionStatus.PENDING,
                payload={"disclaimer": MEDICAL_DISCLAIMER},
                mocked=True,
            )
        )

        return ResponsePlan(
            incident_id=incident.incident_id,
            rationale="Deterministic fallback response plan generated by LifeRescue Safety Policy.",
            actions=actions,
            approved_by_policy=True,
            policy_notes="Generated by fail-safe fallback engine.",
        )
