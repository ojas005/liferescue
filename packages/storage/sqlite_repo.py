"""SQLite Repository implementations for LifeRescue with defense-in-depth redaction.

Implements:
- IncidentRepository
- UserRepository
- ProfileRepository
- ContactRepository
- AuditRepository

Features:
- Pure Python standard library sqlite3 (zero external dependencies).
- Thread-safe connection handling.
- Automatic schema initialization.
- Automatic redaction of secrets on persistence using packages.secrets.redaction.
- Deterministic seeding for demo / local development.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from packages.domain.interfaces import (
    AuditRepository,
    ContactRepository,
    IncidentRepository,
    ProfileRepository,
    UserRepository,
)
from packages.domain.models import (
    AIAnalysis,
    AuditEvent,
    EmergencyContact,
    EmergencyProfile,
    Incident,
    IncidentEvent,
    IncidentStatus,
    ResponseAction,
    ResponseActionStatus,
    ResponseActionType,
    ResponsePlan,
    UrgencyLevel,
    User,
    utcnow,
)
from packages.secrets.redaction import PatternSet, Redactor


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except Exception:
        return utcnow()


class SQLiteDatabase(
    IncidentRepository,
    UserRepository,
    ProfileRepository,
    ContactRepository,
    AuditRepository,
):
    """Unified SQLite repository backing all LifeRescue domain entities."""

    def __init__(
        self, db_path: str | Path = ":memory:", redactor: Redactor | None = None
    ):
        self.db_path = str(db_path)
        self.redactor = redactor or Redactor(patterns=PatternSet.load())
        self._shared_conn: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            self._shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._shared_conn.row_factory = sqlite3.Row
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _sanitize(self, data: Any) -> Any:
        """Apply secret redaction before writing to persistent storage."""
        if isinstance(data, str):
            return self.redactor.redact_text(data, sink="sqlite")
        elif isinstance(data, dict):
            return {k: self._sanitize(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize(item) for item in data]
        return data

    def _dumps(self, data: Any) -> str:
        sanitized = self._sanitize(data)
        return json.dumps(sanitized)

    def _init_db(self) -> None:
        """Create tables if they do not exist."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS emergency_profiles (
                    user_id TEXT PRIMARY KEY,
                    blood_type TEXT,
                    allergies TEXT,
                    medications TEXT,
                    medical_conditions TEXT,
                    emergency_instructions TEXT,
                    primary_language TEXT,
                    home_address TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS emergency_contacts (
                    contact_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    relationship TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    email TEXT,
                    is_primary INTEGER NOT NULL DEFAULT 0,
                    notify_on_escalation INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    input_type TEXT NOT NULL,
                    location TEXT,
                    status TEXT NOT NULL,
                    urgency TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS incident_analyses (
                    analysis_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    category TEXT NOT NULL,
                    urgency TEXT NOT NULL,
                    severity_score INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    immediate_threat INTEGER NOT NULL,
                    extracted_facts TEXT NOT NULL,
                    missing_critical_info TEXT NOT NULL,
                    recommended_immediate_steps TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS response_plans (
                    plan_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    approved_by_policy INTEGER NOT NULL,
                    policy_notes TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    actions_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS incident_events (
                    event_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    incident_id TEXT,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    reason TEXT,
                    request_id TEXT,
                    details_json TEXT NOT NULL
                );

                -- Append-only audit trail: rows can be inserted, never updated or deleted.
                CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                BEFORE UPDATE ON audit_events
                BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

                CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                BEFORE DELETE ON audit_events
                BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
                """
            )
            conn.commit()

    # -------------------------------------------------------------------------
    # User Repository
    # -------------------------------------------------------------------------

    def get(self, user_id: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not row:
                return None
            return User(
                user_id=row["user_id"],
                name=row["name"],
                email=row["email"],
                phone=row["phone"] or "",
                created_at=_parse_dt(row["created_at"]) or utcnow(),
                updated_at=_parse_dt(row["updated_at"]) or utcnow(),
            )

    def save(self, user: User) -> User:
        user.updated_at = utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, name, email, phone, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name = excluded.name,
                    email = excluded.email,
                    phone = excluded.phone,
                    updated_at = excluded.updated_at
                """,
                (
                    user.user_id,
                    self._sanitize(user.name),
                    self._sanitize(user.email),
                    self._sanitize(user.phone),
                    _iso(user.created_at),
                    _iso(user.updated_at),
                ),
            )
            conn.commit()
        return user

    # -------------------------------------------------------------------------
    # Profile Repository
    # -------------------------------------------------------------------------

    def get_profile(self, user_id: str) -> EmergencyProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM emergency_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not row:
                return None
            return EmergencyProfile(
                user_id=row["user_id"],
                blood_type=row["blood_type"] or "",
                allergies=json.loads(row["allergies"] or "[]"),
                medications=json.loads(row["medications"] or "[]"),
                medical_conditions=json.loads(row["medical_conditions"] or "[]"),
                emergency_instructions=row["emergency_instructions"] or "",
                primary_language=row["primary_language"] or "en",
                home_address=row["home_address"] or "",
                updated_at=_parse_dt(row["updated_at"]) or utcnow(),
            )

    # Alias for ProfileRepository interface compatibility
    def get_profile_by_user(self, user_id: str) -> EmergencyProfile | None:
        return self.get_profile(user_id)

    # Implementation for ProfileRepository interface:
    # get(self, user_id: str) -> EmergencyProfile | None
    # We resolve the name clash between UserRepository and ProfileRepository by implementing both:
    def get_user(self, user_id: str) -> User | None:
        return self.get(user_id)

    def save_profile(self, profile: EmergencyProfile) -> EmergencyProfile:
        profile.updated_at = utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO emergency_profiles (
                    user_id, blood_type, allergies, medications, medical_conditions,
                    emergency_instructions, primary_language, home_address, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    blood_type = excluded.blood_type,
                    allergies = excluded.allergies,
                    medications = excluded.medications,
                    medical_conditions = excluded.medical_conditions,
                    emergency_instructions = excluded.emergency_instructions,
                    primary_language = excluded.primary_language,
                    home_address = excluded.home_address,
                    updated_at = excluded.updated_at
                """,
                (
                    profile.user_id,
                    self._sanitize(profile.blood_type),
                    self._dumps(profile.allergies),
                    self._dumps(profile.medications),
                    self._dumps(profile.medical_conditions),
                    self._sanitize(profile.emergency_instructions),
                    profile.primary_language,
                    self._sanitize(profile.home_address),
                    _iso(profile.updated_at),
                ),
            )
            conn.commit()
        return profile

    # -------------------------------------------------------------------------
    # Contact Repository
    # -------------------------------------------------------------------------

    def list_for_user(self, user_id: str) -> list[EmergencyContact]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM emergency_contacts WHERE user_id = ? ORDER BY is_primary DESC, name ASC",
                (user_id,),
            ).fetchall()
            return [
                EmergencyContact(
                    contact_id=r["contact_id"],
                    user_id=r["user_id"],
                    name=r["name"],
                    relationship=r["relationship"],
                    phone=r["phone"],
                    email=r["email"] or "",
                    is_primary=bool(r["is_primary"]),
                    notify_on_escalation=bool(r["notify_on_escalation"]),
                    created_at=_parse_dt(r["created_at"]) or utcnow(),
                    updated_at=_parse_dt(r["updated_at"]) or utcnow(),
                )
                for r in rows
            ]

    def get_contact(self, contact_id: str) -> EmergencyContact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM emergency_contacts WHERE contact_id = ?", (contact_id,)
            ).fetchone()
            if not row:
                return None
            return EmergencyContact(
                contact_id=row["contact_id"],
                user_id=row["user_id"],
                name=row["name"],
                relationship=row["relationship"],
                phone=row["phone"],
                email=row["email"] or "",
                is_primary=bool(row["is_primary"]),
                notify_on_escalation=bool(row["notify_on_escalation"]),
                created_at=_parse_dt(row["created_at"]) or utcnow(),
                updated_at=_parse_dt(row["updated_at"]) or utcnow(),
            )

    def create_contact(self, contact: EmergencyContact) -> EmergencyContact:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO emergency_contacts (
                    contact_id, user_id, name, relationship, phone, email,
                    is_primary, notify_on_escalation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contact.contact_id,
                    contact.user_id,
                    self._sanitize(contact.name),
                    self._sanitize(contact.relationship),
                    self._sanitize(contact.phone),
                    self._sanitize(contact.email),
                    int(contact.is_primary),
                    int(contact.notify_on_escalation),
                    _iso(contact.created_at),
                    _iso(contact.updated_at),
                ),
            )
            conn.commit()
        return contact

    def update_contact(self, contact: EmergencyContact) -> EmergencyContact:
        contact.updated_at = utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE emergency_contacts SET
                    name = ?, relationship = ?, phone = ?, email = ?,
                    is_primary = ?, notify_on_escalation = ?, updated_at = ?
                WHERE contact_id = ?
                """,
                (
                    self._sanitize(contact.name),
                    self._sanitize(contact.relationship),
                    self._sanitize(contact.phone),
                    self._sanitize(contact.email),
                    int(contact.is_primary),
                    int(contact.notify_on_escalation),
                    _iso(contact.updated_at),
                    contact.contact_id,
                ),
            )
            conn.commit()
        return contact

    def delete_contact(self, contact_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM emergency_contacts WHERE contact_id = ?", (contact_id,)
            )
            conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Incident Repository
    # -------------------------------------------------------------------------

    def create(self, incident: Incident) -> Incident:
        incident.title = self._sanitize(incident.title)
        incident.description = self._sanitize(incident.description)
        incident.location = self._sanitize(incident.location)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO incidents (
                    incident_id, user_id, title, description, input_type,
                    location, status, urgency, created_at, updated_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident.incident_id,
                    incident.user_id,
                    incident.title,
                    incident.description,
                    incident.input_type,
                    incident.location,
                    incident.status.value,
                    incident.urgency.value,
                    _iso(incident.created_at),
                    _iso(incident.updated_at),
                    _iso(incident.resolved_at),
                ),
            )
            conn.commit()
        return incident

    def get_incident(self, incident_id: str) -> Incident | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
            ).fetchone()
            if not row:
                return None
            return Incident(
                incident_id=row["incident_id"],
                user_id=row["user_id"],
                title=row["title"],
                description=row["description"],
                input_type=row["input_type"],
                location=row["location"] or "",
                status=IncidentStatus(row["status"]),
                urgency=UrgencyLevel(row["urgency"]),
                created_at=_parse_dt(row["created_at"]) or utcnow(),
                updated_at=_parse_dt(row["updated_at"]) or utcnow(),
                resolved_at=_parse_dt(row["resolved_at"]),
            )

    def list_incidents(
        self, limit: int = 50, user_id: str | None = None
    ) -> list[Incident]:
        with self._connect() as conn:
            if user_id:
                rows = conn.execute(
                    "SELECT * FROM incidents WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()

            return [
                Incident(
                    incident_id=r["incident_id"],
                    user_id=r["user_id"],
                    title=r["title"],
                    description=r["description"],
                    input_type=r["input_type"],
                    location=r["location"] or "",
                    status=IncidentStatus(r["status"]),
                    urgency=UrgencyLevel(r["urgency"]),
                    created_at=_parse_dt(r["created_at"]) or utcnow(),
                    updated_at=_parse_dt(r["updated_at"]) or utcnow(),
                    resolved_at=_parse_dt(r["resolved_at"]),
                )
                for r in rows
            ]

    def update_incident(self, incident: Incident) -> Incident:
        incident.updated_at = utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE incidents SET
                    title = ?, description = ?, location = ?, status = ?,
                    urgency = ?, updated_at = ?, resolved_at = ?
                WHERE incident_id = ?
                """,
                (
                    self._sanitize(incident.title),
                    self._sanitize(incident.description),
                    self._sanitize(incident.location),
                    incident.status.value,
                    incident.urgency.value,
                    _iso(incident.updated_at),
                    _iso(incident.resolved_at),
                    incident.incident_id,
                ),
            )
            conn.commit()
        return incident

    def save_analysis(self, analysis: AIAnalysis) -> AIAnalysis:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO incident_analyses (
                    analysis_id, incident_id, summary, category, urgency,
                    severity_score, confidence, immediate_threat, extracted_facts,
                    missing_critical_info, recommended_immediate_steps, provider_name, analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(analysis_id) DO UPDATE SET
                    summary = excluded.summary,
                    urgency = excluded.urgency,
                    severity_score = excluded.severity_score,
                    confidence = excluded.confidence
                """,
                (
                    analysis.analysis_id,
                    analysis.incident_id,
                    self._sanitize(analysis.summary),
                    analysis.category,
                    analysis.urgency.value,
                    analysis.severity_score,
                    analysis.confidence,
                    int(analysis.immediate_threat),
                    self._dumps(analysis.extracted_facts),
                    self._dumps(analysis.missing_critical_info),
                    self._dumps(analysis.recommended_immediate_steps),
                    analysis.provider_name,
                    _iso(analysis.analyzed_at),
                ),
            )
            conn.commit()
        return analysis

    def get_analysis(self, incident_id: str) -> AIAnalysis | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM incident_analyses WHERE incident_id = ? ORDER BY analyzed_at DESC LIMIT 1",
                (incident_id,),
            ).fetchone()
            if not row:
                return None
            return AIAnalysis(
                analysis_id=row["analysis_id"],
                incident_id=row["incident_id"],
                summary=row["summary"],
                category=row["category"],
                urgency=UrgencyLevel(row["urgency"]),
                severity_score=row["severity_score"],
                confidence=row["confidence"],
                immediate_threat=bool(row["immediate_threat"]),
                extracted_facts=json.loads(row["extracted_facts"]),
                missing_critical_info=json.loads(row["missing_critical_info"]),
                recommended_immediate_steps=json.loads(
                    row["recommended_immediate_steps"]
                ),
                provider_name=row["provider_name"],
                analyzed_at=_parse_dt(row["analyzed_at"]) or utcnow(),
            )

    def save_plan(self, plan: ResponsePlan) -> ResponsePlan:
        actions_data = [
            {
                "action_id": a.action_id,
                "action_type": a.action_type.value,
                "title": a.title,
                "description": a.description,
                "is_escalation": a.is_escalation,
                "requires_confirmation": a.requires_confirmation,
                "status": a.status.value,
                "payload": a.payload,
                "mocked": a.mocked,
                "result_message": a.result_message,
                "executed_at": _iso(a.executed_at),
            }
            for a in plan.actions
        ]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO response_plans (
                    plan_id, incident_id, rationale, approved_by_policy, policy_notes, created_at, actions_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    actions_json = excluded.actions_json,
                    policy_notes = excluded.policy_notes
                """,
                (
                    plan.plan_id,
                    plan.incident_id,
                    self._sanitize(plan.rationale),
                    int(plan.approved_by_policy),
                    self._sanitize(plan.policy_notes),
                    _iso(plan.created_at),
                    self._dumps(actions_data),
                ),
            )
            conn.commit()
        return plan

    def get_plan(self, incident_id: str) -> ResponsePlan | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM response_plans WHERE incident_id = ? ORDER BY created_at DESC LIMIT 1",
                (incident_id,),
            ).fetchone()
            if not row:
                return None
            actions_raw = json.loads(row["actions_json"])
            actions = [
                ResponseAction(
                    action_id=item["action_id"],
                    action_type=ResponseActionType(item["action_type"]),
                    title=item["title"],
                    description=item["description"],
                    is_escalation=item["is_escalation"],
                    requires_confirmation=item["requires_confirmation"],
                    status=ResponseActionStatus(item["status"]),
                    payload=item["payload"],
                    mocked=item.get("mocked", True),
                    result_message=item.get("result_message", ""),
                    executed_at=_parse_dt(item.get("executed_at")),
                )
                for item in actions_raw
            ]
            return ResponsePlan(
                plan_id=row["plan_id"],
                incident_id=row["incident_id"],
                rationale=row["rationale"],
                approved_by_policy=bool(row["approved_by_policy"]),
                policy_notes=row["policy_notes"],
                created_at=_parse_dt(row["created_at"]) or utcnow(),
                actions=actions,
            )

    def append_event(self, event: IncidentEvent) -> IncidentEvent:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO incident_events (
                    event_id, incident_id, seq, timestamp, event_type, actor, summary, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.incident_id,
                    event.seq,
                    _iso(event.timestamp),
                    event.event_type,
                    event.actor,
                    self._sanitize(event.summary),
                    self._dumps(event.payload),
                ),
            )
            conn.commit()
        return event

    def get_timeline(self, incident_id: str) -> list[IncidentEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM incident_events WHERE incident_id = ? ORDER BY seq ASC",
                (incident_id,),
            ).fetchall()
            return [
                IncidentEvent(
                    event_id=r["event_id"],
                    incident_id=r["incident_id"],
                    seq=r["seq"],
                    timestamp=_parse_dt(r["timestamp"]) or utcnow(),
                    event_type=r["event_type"],
                    actor=r["actor"],
                    summary=r["summary"],
                    payload=json.loads(r["payload_json"]),
                )
                for r in rows
            ]

    # -------------------------------------------------------------------------
    # Audit Repository
    # -------------------------------------------------------------------------

    def record(self, event: AuditEvent) -> AuditEvent:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    event_id, timestamp, event_type, actor, incident_id, action, result, reason, request_id, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    _iso(event.timestamp),
                    event.event_type,
                    event.actor,
                    event.incident_id,
                    event.action,
                    event.result,
                    self._sanitize(event.reason),
                    event.request_id,
                    self._dumps(event.details),
                ),
            )
            conn.commit()
        return event

    def list_audit(
        self, limit: int = 100, incident_id: str | None = None
    ) -> list[AuditEvent]:
        with self._connect() as conn:
            if incident_id:
                rows = conn.execute(
                    "SELECT * FROM audit_events WHERE incident_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (incident_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()

            return [
                AuditEvent(
                    event_id=r["event_id"],
                    timestamp=_parse_dt(r["timestamp"]) or utcnow(),
                    event_type=r["event_type"],
                    actor=r["actor"],
                    incident_id=r["incident_id"],
                    action=r["action"],
                    result=r["result"],
                    reason=r["reason"] or "",
                    request_id=r["request_id"] or "",
                    details=json.loads(r["details_json"]),
                )
                for r in rows
            ]

    # Explicit interface adapters:
    # IncidentRepository:
    def update(self, incident: Incident) -> Incident:
        return self.update_incident(incident)

    def list(self, limit: int = 50, user_id: str | None = None) -> list[Incident]:
        return self.list_incidents(limit, user_id)

    # ContactRepository:
    def get_contact_by_id(self, contact_id: str) -> EmergencyContact | None:
        return self.get_contact(contact_id)

    def create_contact_record(self, contact: EmergencyContact) -> EmergencyContact:
        return self.create_contact(contact)

    def update_contact_record(self, contact: EmergencyContact) -> EmergencyContact:
        return self.update_contact(contact)

    def delete(self, contact_id: str) -> bool:
        return self.delete_contact(contact_id)

    def reset_demo_data(self, user_id: str = "usr_demo") -> dict[str, int]:
        """Remove demo incidents, plans, events, analyses. Audit events are append-only and never deleted (SEC-05)."""
        counts: dict[str, int] = {}
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT incident_id FROM incidents WHERE user_id = ?", (user_id,)
            )
            incident_ids = [row["incident_id"] for row in cursor.fetchall()]

            if incident_ids:
                placeholders = ",".join("?" for _ in incident_ids)
                counts["events"] = conn.execute(
                    f"DELETE FROM incident_events WHERE incident_id IN ({placeholders})",
                    incident_ids,
                ).rowcount
                counts["plans"] = conn.execute(
                    f"DELETE FROM response_plans WHERE incident_id IN ({placeholders})",
                    incident_ids,
                ).rowcount
                counts["analyses"] = conn.execute(
                    f"DELETE FROM incident_analyses WHERE incident_id IN ({placeholders})",
                    incident_ids,
                ).rowcount
                counts["incidents"] = conn.execute(
                    "DELETE FROM incidents WHERE user_id = ?", (user_id,)
                ).rowcount
            else:
                counts["events"] = 0
                counts["plans"] = 0
                counts["analyses"] = 0
                counts["incidents"] = 0

            conn.commit()
        return counts


class ProfileRepoAdapter(ProfileRepository):
    """Adapter exposing ProfileRepository interface on top of SQLiteDatabase."""

    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def get(self, user_id: str) -> EmergencyProfile | None:
        return self.db.get_profile(user_id)

    def save(self, profile: EmergencyProfile) -> EmergencyProfile:
        return self.db.save_profile(profile)


class ContactRepoAdapter(ContactRepository):
    """Adapter exposing ContactRepository interface on top of SQLiteDatabase."""

    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def list_for_user(self, user_id: str) -> list[EmergencyContact]:
        return self.db.list_for_user(user_id)

    def get(self, contact_id: str) -> EmergencyContact | None:
        return self.db.get_contact(contact_id)

    def create(self, contact: EmergencyContact) -> EmergencyContact:
        return self.db.create_contact(contact)

    def update(self, contact: EmergencyContact) -> EmergencyContact:
        return self.db.update_contact(contact)

    def delete(self, contact_id: str) -> bool:
        return self.db.delete_contact(contact_id)


class UserRepoAdapter(UserRepository):
    """Adapter exposing UserRepository interface on top of SQLiteDatabase."""

    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def get(self, user_id: str) -> User | None:
        return self.db.get_user(user_id)

    def save(self, user: User) -> User:
        return self.db.save(user)


class IncidentRepoAdapter(IncidentRepository):
    """Adapter exposing IncidentRepository interface on top of SQLiteDatabase."""

    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def create(self, incident: Incident) -> Incident:
        return self.db.create(incident)

    def get(self, incident_id: str) -> Incident | None:
        return self.db.get_incident(incident_id)

    def list(self, limit: int = 50, user_id: str | None = None) -> list[Incident]:
        return self.db.list_incidents(limit, user_id)

    def update(self, incident: Incident) -> Incident:
        return self.db.update_incident(incident)

    def save_analysis(self, analysis: AIAnalysis) -> AIAnalysis:
        return self.db.save_analysis(analysis)

    def get_analysis(self, incident_id: str) -> AIAnalysis | None:
        return self.db.get_analysis(incident_id)

    def save_plan(self, plan: ResponsePlan) -> ResponsePlan:
        return self.db.save_plan(plan)

    def get_plan(self, incident_id: str) -> ResponsePlan | None:
        return self.db.get_plan(incident_id)

    def append_event(self, event: IncidentEvent) -> IncidentEvent:
        return self.db.append_event(event)

    def get_timeline(self, incident_id: str) -> list[IncidentEvent]:
        return self.db.get_timeline(incident_id)


class AuditRepoAdapter(AuditRepository):
    """Adapter exposing AuditRepository interface on top of SQLiteDatabase."""

    def __init__(self, db: SQLiteDatabase):
        self.db = db

    def record(self, event: AuditEvent) -> AuditEvent:
        return self.db.record(event)

    def list(
        self, limit: int = 100, incident_id: str | None = None
    ) -> list[AuditEvent]:
        return self.db.list_audit(limit, incident_id)


def create_repositories(
    db: SQLiteDatabase,
) -> tuple[
    IncidentRepoAdapter,
    UserRepoAdapter,
    ProfileRepoAdapter,
    ContactRepoAdapter,
    AuditRepoAdapter,
]:
    """Create all five domain repository adapters from an SQLite instance."""
    return (
        IncidentRepoAdapter(db),
        UserRepoAdapter(db),
        ProfileRepoAdapter(db),
        ContactRepoAdapter(db),
        AuditRepoAdapter(db),
    )
