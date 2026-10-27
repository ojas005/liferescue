"""Dependency injection container for LifeRescue FastAPI application."""

from __future__ import annotations

import logging

from apps.api.config import Settings, get_settings
from packages.domain.ai import create_ai_provider
from packages.domain.models import EmergencyContact, EmergencyProfile, User
from packages.domain.orchestrator import MockNotificationProvider, ResponseOrchestrator
from packages.domain.safety_policy import SafetyPolicyEngine
from packages.secrets.leased_values import LeasedValues
from packages.secrets.redaction import PatternSet, Redactor
from packages.storage.sqlite_repo import (
    SQLiteDatabase,
    create_repositories,
)

logger = logging.getLogger("liferescue.deps")

# Global singleton storage and services
_db: SQLiteDatabase | None = None
_orchestrator: ResponseOrchestrator | None = None
_leased_values: LeasedValues = LeasedValues()
_redactor: Redactor | None = None


def get_leased_values() -> LeasedValues:
    return _leased_values


def get_redactor(redactor: Redactor | None = None) -> Redactor:
    global _redactor
    if redactor is not None:
        _redactor = redactor
    elif _redactor is None:
        _redactor = Redactor(leased_values=_leased_values, patterns=PatternSet.load())
    return _redactor


def init_dependencies(
    settings: Settings | None = None,
) -> tuple[SQLiteDatabase, ResponseOrchestrator]:
    """Initialize database and orchestrator with specific settings."""
    global _db, _orchestrator
    s = settings or get_settings()
    _db = SQLiteDatabase(db_path=s.db_path, redactor=get_redactor())
    _seed_demo_data(_db)
    inc_repo, _user_repo, profile_repo, contact_repo, audit_repo = create_repositories(
        _db
    )
    ai = create_ai_provider(s.ai_provider, s)
    safety = SafetyPolicyEngine()
    notifications = MockNotificationProvider()

    _orchestrator = ResponseOrchestrator(
        incident_repo=inc_repo,
        profile_repo=profile_repo,
        contact_repo=contact_repo,
        audit_repo=audit_repo,
        ai_provider=ai,
        safety_engine=safety,
        notification_provider=notifications,
    )
    return _db, _orchestrator


def get_db() -> SQLiteDatabase:
    if _db is None:
        init_dependencies()
    return _db


def _seed_demo_data(db: SQLiteDatabase, force: bool = False) -> None:
    """Seed initial demo user and profile if not already populated or on forced reset."""
    _inc_repo, user_repo, profile_repo, contact_repo, _audit_repo = create_repositories(
        db
    )
    demo_user = user_repo.get("usr_demo")
    if not demo_user or force:
        logger.info("Seeding initial LifeRescue demo user, profile, and contacts")
        user_repo.save(
            User(
                user_id="usr_demo",
                name="Alex Chen",
                email="alex.chen@example.com",
                phone="+1-555-0144",
            )
        )
        profile_repo.save(
            EmergencyProfile(
                user_id="usr_demo",
                blood_type="O+",
                allergies=["Penicillin", "Peanuts"],
                medications=["Albuterol inhaler (as needed)"],
                medical_conditions=["Mild exercise-induced asthma"],
                emergency_instructions="Spare inhaler is located in backpack outer pocket. Building gate code is #4821.",
                primary_language="en",
                home_address="742 Evergreen Terrace, Springfield",
            )
        )
        # Reset contacts to deterministic pair
        existing_contacts = contact_repo.list_for_user("usr_demo")
        for c in existing_contacts:
            contact_repo.delete(c.contact_id)
        contact_repo.create(
            EmergencyContact(
                contact_id="cnt_primary",
                user_id="usr_demo",
                name="Sarah Chen",
                relationship="Spouse",
                phone="+1-555-0199",
                email="sarah.chen@example.com",
                is_primary=True,
                notify_on_escalation=True,
            )
        )
        contact_repo.create(
            EmergencyContact(
                contact_id="cnt_secondary",
                user_id="usr_demo",
                name="Dr. Marcus Bell",
                relationship="Primary Physician",
                phone="+1-555-0182",
                email="marcus.bell@springfieldclinic.org",
                is_primary=False,
                notify_on_escalation=False,
            )
        )


def get_orchestrator() -> ResponseOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        s = get_settings()
        db = get_db()
        inc_repo, _user_repo, profile_repo, contact_repo, audit_repo = (
            create_repositories(db)
        )
        ai = create_ai_provider(s.ai_provider, s)
        safety = SafetyPolicyEngine()
        notifications = MockNotificationProvider()

        _orchestrator = ResponseOrchestrator(
            incident_repo=inc_repo,
            profile_repo=profile_repo,
            contact_repo=contact_repo,
            audit_repo=audit_repo,
            ai_provider=ai,
            safety_engine=safety,
            notification_provider=notifications,
        )
    return _orchestrator


def reset_for_tests(
    db_path: str = ":memory:",
    redactor: Redactor | None = None,
) -> ResponseOrchestrator:
    """Reset singletons with an isolated in-memory database for testing."""
    global _db, _orchestrator, _redactor, _leased_values
    _leased_values = LeasedValues()
    _redactor = redactor or Redactor(
        leased_values=_leased_values, patterns=PatternSet.load()
    )
    _db = SQLiteDatabase(db_path=db_path, redactor=_redactor)
    _seed_demo_data(_db)
    inc_repo, _user_repo, profile_repo, contact_repo, audit_repo = create_repositories(
        _db
    )
    ai = create_ai_provider("mock")
    safety = SafetyPolicyEngine()
    notifications = MockNotificationProvider()

    _orchestrator = ResponseOrchestrator(
        incident_repo=inc_repo,
        profile_repo=profile_repo,
        contact_repo=contact_repo,
        audit_repo=audit_repo,
        ai_provider=ai,
        safety_engine=safety,
        notification_provider=notifications,
    )
    return _orchestrator
