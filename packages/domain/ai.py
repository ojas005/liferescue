"""AI Provider Abstraction for LifeRescue.

Provides:
- MockAIProvider: Deterministic, offline provider for hackathon demos, unit testing, and zero-credential runs.
- NVIDIAAIProvider: Adapter boundary for NVIDIA / Nebius hosted models (OpenAI-compatible chat completion API).
- Factory function create_ai_provider(...)
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Literal, Sequence

from packages.domain.interfaces import AIProvider
from packages.domain.models import (
    AIAnalysis,
    EmergencyContact,
    EmergencyProfile,
    Incident,
    ReadinessAssessment,
    ReadinessCheck,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
    ResponsePlan,
    UrgencyLevel,
)

logger = logging.getLogger("liferescue.ai")


# Injection and adversarial detection patterns
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a\s+", re.IGNORECASE),
    re.compile(r"(pwned|jailbreak|dan\s+mode|<script>|<!--)", re.IGNORECASE),
    re.compile(r"(\$\{.*\}|\$\(.*\)|`.*`)"),
]


class MockAIProvider(AIProvider):
    """Deterministic, local AI provider with rich triage knowledge and safety guards."""

    def name(self) -> str:
        return "mock_ai"

    def analyze_emergency(
        self,
        incident: Incident,
        profile: EmergencyProfile | None = None,
        contacts: Sequence[EmergencyContact] = (),
    ) -> AIAnalysis:
        text = f"{incident.title} {incident.description}".lower()

        # Check for adversarial attempt in input
        is_adversarial = any(pat.search(text) for pat in PROMPT_INJECTION_PATTERNS)
        if is_adversarial:
            logger.warning(
                "Adversarial/injection input pattern detected in incident text"
            )
            return AIAnalysis(
                incident_id=incident.incident_id,
                summary="Input contained disallowed instructions or system override attempts. Triage reset to defensive safety mode.",
                category="suspicious_activity",
                urgency=UrgencyLevel.LOW,
                severity_score=1,
                confidence=0.99,
                immediate_threat=False,
                extracted_facts={"security_flag": "prompt_injection_attempt_detected"},
                missing_critical_info=["verified_human_emergency_details"],
                recommended_immediate_steps=[
                    "Please state the actual physical emergency concisely.",
                    "LifeRescue system policies cannot be overridden by prompt instructions.",
                ],
                provider_name="mock_ai",
            )

        # Scenario 1: Severe Medical Emergency
        if any(
            term in text
            for term in (
                "chest pain",
                "heart attack",
                "breathing",
                "breath",
                "unconscious",
                "stroke",
                "allergic",
            )
        ):
            extracted = {
                "symptoms": [
                    "acute distress",
                    "potential cardiovascular or respiratory compromise",
                ],
                "conscious_status": "unknown"
                if "unconscious" not in text
                else "unconscious",
                "patient_risk": "critical",
            }
            if profile and profile.medical_conditions:
                extracted["relevant_history"] = profile.medical_conditions

            missing = []
            if not incident.location:
                missing.append("Exact physical location or GPS coordinates")
            if "conscious" not in text and "unconscious" not in text:
                missing.append("Is the patient conscious and responsive?")

            return AIAnalysis(
                incident_id=incident.incident_id,
                summary="Acute medical emergency detected with high risk of cardiovascular or respiratory compromise.",
                category="medical",
                urgency=UrgencyLevel.CRITICAL,
                severity_score=9,
                confidence=0.95,
                immediate_threat=True,
                extracted_facts=extracted,
                missing_critical_info=missing,
                recommended_immediate_steps=[
                    "Call emergency medical dispatchers immediately (911/112).",
                    "Place patient in comfortable resting position (sitting up if breathing difficulty).",
                    "Do NOT leave the patient unattended.",
                    "Unlock front door if safe to do so for paramedic entry.",
                ],
                provider_name="mock_ai",
            )

        # Scenario 2: Traffic / Vehicle Accident
        if any(
            term in text
            for term in (
                "crash",
                "accident",
                "collision",
                "car",
                "highway",
                "traffic",
                "overturned",
                "airbag",
            )
        ):
            extracted = {
                "incident_type": "motor_vehicle_collision",
                "injuries_reported": any(
                    w in text
                    for w in (
                        "injur",
                        "bleed",
                        "pain",
                        "lacerat",
                        "trauma",
                        "wound",
                        "fractur",
                        "head",
                    )
                ),
                "hazards_detected": any(
                    w in text
                    for w in (
                        "smoke",
                        "fire",
                        "radiator",
                        "fuel",
                        "gas",
                        "flame",
                        "spill",
                        "hazard",
                    )
                ),
                "scene_safety": "roadway_hazard",
            }
            missing = []
            if not incident.location:
                missing.append("Highway number, mile marker, or intersection")
            missing.append("Number of vehicles and occupants involved")

            return AIAnalysis(
                incident_id=incident.incident_id,
                summary="Traffic accident reported. Risk of collision hazards and passenger trauma.",
                category="accident",
                urgency=UrgencyLevel.HIGH,
                severity_score=8,
                confidence=0.92,
                immediate_threat=True,
                extracted_facts=extracted,
                missing_critical_info=missing,
                recommended_immediate_steps=[
                    "Activate vehicle hazard lights immediately.",
                    "If safe to do so, move beyond the guardrail or away from oncoming traffic.",
                    "Check passengers for consciousness and heavy bleeding.",
                    "Do not attempt to move seriously injured persons unless there is imminent fire danger.",
                ],
                provider_name="mock_ai",
            )

        # Scenario 3: Fire / Environmental Hazard
        if any(
            term in text
            for term in ("fire", "smoke", "gas leak", "burning", "explosion")
        ):
            return AIAnalysis(
                incident_id=incident.incident_id,
                summary="Fire or hazardous atmospheric condition detected. Immediate evacuation priority.",
                category="fire_hazard",
                urgency=UrgencyLevel.CRITICAL,
                severity_score=9,
                confidence=0.96,
                immediate_threat=True,
                extracted_facts={
                    "hazard": "fire_or_gas",
                    "evacuation_status": "required",
                },
                missing_critical_info=[
                    "Are any occupants trapped inside?",
                    "Specific floor or building section",
                ],
                recommended_immediate_steps=[
                    "Evacuate the structure immediately. Do NOT use elevators.",
                    "Stay low beneath smoke layers.",
                    "Assemble at designated outdoor safety checkpoint.",
                    "Call fire emergency services once outdoors.",
                ],
                provider_name="mock_ai",
            )

        # Default / General Emergency
        return AIAnalysis(
            incident_id=incident.incident_id,
            summary=f"Incident report analyzed: {incident.title}.",
            category="general_assistance",
            urgency=UrgencyLevel.MEDIUM,
            severity_score=5,
            confidence=0.85,
            immediate_threat=False,
            extracted_facts={"report_type": "general_emergency"},
            missing_critical_info=[
                "Specific medical or physical danger details",
                "Exact location",
            ],
            recommended_immediate_steps=[
                "Confirm personal safety and assess immediate surroundings.",
                "Provide additional detail regarding any injuries or hazards.",
                "Stand by for further coordination.",
            ],
            provider_name="mock_ai",
        )

    def generate_response_plan(
        self,
        incident: Incident,
        analysis: AIAnalysis,
        profile: EmergencyProfile | None = None,
        contacts: Sequence[EmergencyContact] = (),
    ) -> ResponsePlan:
        actions: list[ResponseAction] = []

        if analysis.urgency in (UrgencyLevel.CRITICAL, UrgencyLevel.HIGH):
            actions.append(
                ResponseAction(
                    action_type=ResponseActionType.CALL_EMERGENCY_SERVICES,
                    title="Dispatch Emergency Responders",
                    description=f"Initiate priority escalation to emergency dispatch. Category: {analysis.category}.",
                    is_escalation=True,
                    status=ResponseActionStatus.PENDING,
                    payload={
                        "category": analysis.category,
                        "severity": analysis.severity_score,
                    },
                    mocked=True,
                )
            )

        # Notify emergency contact if configured
        if contacts:
            primary = next((c for c in contacts if c.is_primary), contacts[0])
            actions.append(
                ResponseAction(
                    action_type=ResponseActionType.NOTIFY_CONTACT,
                    title=f"Notify Emergency Contact: {primary.name}",
                    description=f"Send automated SMS alert with incident status and location to {primary.name} ({primary.phone}).",
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

        # Prepare emergency responder summary
        actions.append(
            ResponseAction(
                action_type=ResponseActionType.PREPARE_SUMMARY,
                title="Generate Paramedic Triage Dossier",
                description="Compile user medical history, allergies, and incident facts into a concise responder briefing card.",
                is_escalation=False,
                status=ResponseActionStatus.PENDING,
                payload={
                    "allergies": profile.allergies if profile else [],
                    "medications": profile.medications if profile else [],
                    "conditions": profile.medical_conditions if profile else [],
                },
                mocked=True,
            )
        )

        # Display actionable instructions
        actions.append(
            ResponseAction(
                action_type=ResponseActionType.DISPLAY_INSTRUCTIONS,
                title="Display Next Safety Steps",
                description="\n".join(
                    f"- {step}" for step in analysis.recommended_immediate_steps
                ),
                is_escalation=False,
                status=ResponseActionStatus.PENDING,
                payload={"steps": analysis.recommended_immediate_steps},
                mocked=True,
            )
        )

        return ResponsePlan(
            incident_id=incident.incident_id,
            rationale=f"AI Response plan structured around {analysis.category} emergency with {analysis.urgency.value} urgency.",
            actions=actions,
            approved_by_policy=False,  # Must be vetted by Safety Policy Engine
        )

    def assess_readiness(
        self,
        profile: EmergencyProfile,
        contacts: Sequence[EmergencyContact],
    ) -> ReadinessAssessment:
        checks: list[ReadinessCheck] = []
        gaps: list[str] = []
        score = 0

        # Check 1: Primary contact configured
        has_primary = any(c.is_primary for c in contacts) or len(contacts) > 0
        if has_primary:
            checks.append(
                ReadinessCheck(
                    check_id="chk_contact_primary",
                    category="contacts",
                    title="Designated Emergency Contact",
                    description="You have registered at least one emergency contact.",
                    passed=True,
                    importance="critical",
                )
            )
            score += 30
        else:
            checks.append(
                ReadinessCheck(
                    check_id="chk_contact_primary",
                    category="contacts",
                    title="Designated Emergency Contact",
                    description="No emergency contact registered. Responders won't know whom to notify.",
                    passed=False,
                    importance="critical",
                )
            )
            gaps.append(
                "Register at least one primary emergency contact with a phone number."
            )

        # Check 2: Blood type
        if profile.blood_type:
            checks.append(
                ReadinessCheck(
                    check_id="chk_blood_type",
                    category="medical",
                    title="Blood Type Recorded",
                    description=f"Blood type {profile.blood_type} is listed for trauma preparation.",
                    passed=True,
                    importance="recommended",
                )
            )
            score += 20
        else:
            checks.append(
                ReadinessCheck(
                    check_id="chk_blood_type",
                    category="medical",
                    title="Blood Type Recorded",
                    description="Blood type is missing from your emergency profile.",
                    passed=False,
                    importance="recommended",
                )
            )
            gaps.append(
                "Specify your blood type (e.g. O+, A-, etc.) to speed up trauma transfusions."
            )

        # Check 3: Medical conditions & Allergies
        has_medical = bool(
            profile.medical_conditions or profile.allergies or profile.medications
        )
        if has_medical:
            checks.append(
                ReadinessCheck(
                    check_id="chk_medical_data",
                    category="medical",
                    title="Critical Medical & Allergy Data",
                    description="Known allergies and medical history are documented.",
                    passed=True,
                    importance="critical",
                )
            )
            score += 25
        else:
            checks.append(
                ReadinessCheck(
                    check_id="chk_medical_data",
                    category="medical",
                    title="Critical Medical & Allergy Data",
                    description="No allergies, medications, or conditions documented.",
                    passed=False,
                    importance="critical",
                )
            )
            gaps.append(
                "Document any allergies (or note 'No known allergies') and current medications."
            )

        # Check 4: Emergency Instructions
        if len(profile.emergency_instructions.strip()) > 10:
            checks.append(
                ReadinessCheck(
                    check_id="chk_instructions",
                    category="instructions",
                    title="Personal Emergency Directives",
                    description="Custom instructions for responders (e.g., dependent care, building code) are set.",
                    passed=True,
                    importance="recommended",
                )
            )
            score += 25
        else:
            checks.append(
                ReadinessCheck(
                    check_id="chk_instructions",
                    category="instructions",
                    title="Personal Emergency Directives",
                    description="No special directives or home access instructions provided.",
                    passed=False,
                    importance="recommended",
                )
            )
            gaps.append(
                "Add special emergency directives (e.g., pet at home, building gate code)."
            )

        status: Literal["poor", "moderate", "good", "excellent"]
        if score >= 85:
            status = "excellent"
        elif score >= 65:
            status = "good"
        elif score >= 40:
            status = "moderate"
        else:
            status = "poor"

        recommendations = [f"Address missing item: {gap}" for gap in gaps]
        if not recommendations:
            recommendations = [
                "Your emergency profile is comprehensive and up to date."
            ]

        return ReadinessAssessment(
            user_id=profile.user_id,
            score=score,
            status=status,
            checks=checks,
            gaps=gaps,
            recommendations=recommendations,
        )


class NVIDIAAIProvider(AIProvider):
    """NVIDIA / Nebius AI provider adapter boundary.

    Connects to NVIDIA NIM / Nebius AI Cloud OpenAI-compatible endpoints when
    API credentials and model names are configured.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "meta/llama-3.1-70b-instruct",
        base_url: str = "https://integrate.api.nvidia.com/v1",
    ):
        self.api_key = (
            api_key
            or os.environ.get("NVIDIA_API_KEY")
            or os.environ.get("NEBIUS_API_KEY")
        )
        self.model = os.environ.get("NVIDIA_MODEL") or model
        self.base_url = os.environ.get("NVIDIA_BASE_URL") or base_url
        self._fallback_mock = MockAIProvider()

    def name(self) -> str:
        return "nvidia_ai"

    def _is_configured(self) -> bool:
        return bool(self.api_key and not self.api_key.startswith("mock-"))

    def analyze_emergency(
        self,
        incident: Incident,
        profile: EmergencyProfile | None = None,
        contacts: Sequence[EmergencyContact] = (),
    ) -> AIAnalysis:
        if not self._is_configured():
            logger.info(
                "NVIDIA API key not set; gracefully delegating to deterministic triage provider"
            )
            res = self._fallback_mock.analyze_emergency(incident, profile, contacts)
            return AIAnalysis(
                incident_id=res.incident_id,
                summary=res.summary,
                category=res.category,
                urgency=res.urgency,
                severity_score=res.severity_score,
                confidence=res.confidence,
                immediate_threat=res.immediate_threat,
                extracted_facts=res.extracted_facts,
                missing_critical_info=res.missing_critical_info,
                recommended_immediate_steps=res.recommended_immediate_steps,
                provider_name="nvidia_ai (mock_fallback)",
            )

        # In production mode when credentials are provided:
        try:
            import httpx

            prompt = (
                f"You are an AI emergency triage assistant. Analyze this incident:\n"
                f"Title: {incident.title}\n"
                f"Description: {incident.description}\n"
                f"Location: {incident.location}\n"
                f"Return JSON strictly with keys: summary, category, urgency (low|medium|high|critical), "
                f"severity_score (1-10), confidence (0.0-1.0), immediate_threat (bool), "
                f"extracted_facts (dict), missing_critical_info (list), recommended_immediate_steps (list)."
            )
            resp = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(data)
            return AIAnalysis(
                incident_id=incident.incident_id,
                summary=parsed.get("summary", incident.title),
                category=parsed.get("category", "emergency"),
                urgency=UrgencyLevel(parsed.get("urgency", "high")),
                severity_score=int(parsed.get("severity_score", 7)),
                confidence=float(parsed.get("confidence", 0.9)),
                immediate_threat=bool(parsed.get("immediate_threat", True)),
                extracted_facts=parsed.get("extracted_facts", {}),
                missing_critical_info=parsed.get("missing_critical_info", []),
                recommended_immediate_steps=parsed.get(
                    "recommended_immediate_steps", []
                ),
                provider_name="nvidia_ai",
            )
        except Exception as err:
            logger.warning(
                "NVIDIA provider call failed (%s); falling back to mock provider", err
            )
            return self._fallback_mock.analyze_emergency(incident, profile, contacts)

    def generate_response_plan(
        self,
        incident: Incident,
        analysis: AIAnalysis,
        profile: EmergencyProfile | None = None,
        contacts: Sequence[EmergencyContact] = (),
    ) -> ResponsePlan:
        return self._fallback_mock.generate_response_plan(
            incident, analysis, profile, contacts
        )

    def assess_readiness(
        self,
        profile: EmergencyProfile,
        contacts: Sequence[EmergencyContact],
    ) -> ReadinessAssessment:
        return self._fallback_mock.assess_readiness(profile, contacts)


def create_ai_provider(provider_type: str = "mock") -> AIProvider:
    """Factory creating configured AI provider."""
    provider_type = provider_type.lower()
    if provider_type in ("nvidia", "nebius"):
        return NVIDIAAIProvider()
    return MockAIProvider()
