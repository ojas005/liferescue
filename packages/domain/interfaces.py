"""LifeRescue Domain Interfaces.

Explicit abstract interfaces decouple business logic from external providers,
database engines, and notification mechanisms.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from packages.domain.models import (
    AIAnalysis,
    AuditEvent,
    EmergencyContact,
    EmergencyProfile,
    Incident,
    IncidentEvent,
    ReadinessAssessment,
    ResponseAction,
    ResponsePlan,
    User,
)


class AIProvider(ABC):
    """Abstract interface for AI intelligence providers (Mock, NVIDIA/Nebius)."""

    @abstractmethod
    def name(self) -> str:
        """Name of the provider implementation."""
        pass

    @abstractmethod
    def analyze_emergency(
        self,
        incident: Incident,
        profile: EmergencyProfile | None = None,
        contacts: Sequence[EmergencyContact] = (),
    ) -> AIAnalysis:
        """Perform semantic understanding, urgency classification, and triage analysis."""
        pass

    @abstractmethod
    def generate_response_plan(
        self,
        incident: Incident,
        analysis: AIAnalysis,
        profile: EmergencyProfile | None = None,
        contacts: Sequence[EmergencyContact] = (),
    ) -> ResponsePlan:
        """Generate structured response actions for the incident."""
        pass

    @abstractmethod
    def assess_readiness(
        self,
        profile: EmergencyProfile,
        contacts: Sequence[EmergencyContact],
    ) -> ReadinessAssessment:
        """Evaluate user emergency preparedness and suggest actions."""
        pass


class NotificationProvider(ABC):
    """Abstract interface for dispatching notifications / escalations."""

    @abstractmethod
    def is_mock(self) -> bool:
        """True if the provider is a simulation."""
        pass

    @abstractmethod
    def dispatch_action(
        self,
        action: ResponseAction,
        incident: Incident,
        profile: EmergencyProfile | None = None,
    ) -> tuple[bool, str]:
        """Dispatch or simulate an action. Returns (success, result_message)."""
        pass


class IncidentRepository(ABC):
    """Storage repository for incidents and timeline events."""

    @abstractmethod
    def create(self, incident: Incident) -> Incident:
        pass

    @abstractmethod
    def get(self, incident_id: str) -> Incident | None:
        pass

    @abstractmethod
    def list(self, limit: int = 50, user_id: str | None = None) -> list[Incident]:
        pass

    @abstractmethod
    def update(self, incident: Incident) -> Incident:
        pass

    @abstractmethod
    def save_analysis(self, analysis: AIAnalysis) -> AIAnalysis:
        pass

    @abstractmethod
    def get_analysis(self, incident_id: str) -> AIAnalysis | None:
        pass

    @abstractmethod
    def save_plan(self, plan: ResponsePlan) -> ResponsePlan:
        pass

    @abstractmethod
    def get_plan(self, incident_id: str) -> ResponsePlan | None:
        pass

    @abstractmethod
    def append_event(self, event: IncidentEvent) -> IncidentEvent:
        pass

    @abstractmethod
    def get_timeline(self, incident_id: str) -> list[IncidentEvent]:
        pass


class UserRepository(ABC):
    """Storage repository for user entity."""

    @abstractmethod
    def get(self, user_id: str) -> User | None:
        pass

    @abstractmethod
    def save(self, user: User) -> User:
        pass


class ProfileRepository(ABC):
    """Storage repository for emergency profile."""

    @abstractmethod
    def get(self, user_id: str) -> EmergencyProfile | None:
        pass

    @abstractmethod
    def save(self, profile: EmergencyProfile) -> EmergencyProfile:
        pass


class ContactRepository(ABC):
    """Storage repository for emergency contacts."""

    @abstractmethod
    def list_for_user(self, user_id: str) -> list[EmergencyContact]:
        pass

    @abstractmethod
    def get(self, contact_id: str) -> EmergencyContact | None:
        pass

    @abstractmethod
    def create(self, contact: EmergencyContact) -> EmergencyContact:
        pass

    @abstractmethod
    def update(self, contact: EmergencyContact) -> EmergencyContact:
        pass

    @abstractmethod
    def delete(self, contact_id: str) -> bool:
        pass


class AuditRepository(ABC):
    """Storage repository for audit records."""

    @abstractmethod
    def record(self, event: AuditEvent) -> AuditEvent:
        pass

    @abstractmethod
    def list(
        self, limit: int = 100, incident_id: str | None = None
    ) -> list[AuditEvent]:
        pass
