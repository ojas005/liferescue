"""Unit tests for SQLite storage repositories and persistence redaction."""

import unittest

from packages.domain.models import AuditEvent, EmergencyContact, Incident, User
from packages.secrets.testing import random_chars
from packages.storage.sqlite_repo import SQLiteDatabase, create_repositories


class TestSQLiteStorage(unittest.TestCase):
    def setUp(self):
        self.db = SQLiteDatabase(":memory:")
        (
            self.inc_repo,
            self.user_repo,
            self.profile_repo,
            self.contact_repo,
            self.audit_repo,
        ) = create_repositories(self.db)

    def test_user_persistence(self):
        user = User(
            user_id="u_test",
            name="Carol Danvers",
            email="carol@test.com",
            phone="+1000",
        )
        self.user_repo.save(user)
        fetched = self.user_repo.get("u_test")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Carol Danvers")
        self.assertEqual(fetched.email, "carol@test.com")

    def test_contact_crud(self):
        c = EmergencyContact(
            user_id="u_test", name="Nick", relationship="Colleague", phone="123"
        )
        created = self.contact_repo.create(c)
        self.assertEqual(created.name, "Nick")

        # List
        contacts = self.contact_repo.list_for_user("u_test")
        self.assertEqual(len(contacts), 1)

        # Update
        created.phone = "999"
        self.contact_repo.update(created)
        updated = self.contact_repo.get(created.contact_id)
        self.assertEqual(updated.phone, "999")

        # Delete
        deleted = self.contact_repo.delete(created.contact_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.contact_repo.get(created.contact_id))

    def test_secret_redacted_before_db_write(self):
        # Place seeded fake xai/nvapi credentials into description and medical instructions
        canary_key = "xai-" + random_chars(44)
        inc = Incident(
            title="Incident with canary", description=f"The secret is {canary_key}"
        )
        self.inc_repo.create(inc)

        # Retrieve direct raw row
        with self.db._connect() as conn:
            row = conn.execute(
                "SELECT description FROM incidents WHERE incident_id = ?",
                (inc.incident_id,),
            ).fetchone()
            self.assertNotIn(canary_key, row["description"])
            self.assertIn("[REDACTED:xai_key]", row["description"])

    def test_audit_event_logging_and_redaction(self):
        canary = "nvapi-" + random_chars(48)
        event = AuditEvent(
            event_type="TEST_EVENT",
            actor="tester",
            action="verify_redaction",
            result="success",
            reason=f"Processing key {canary}",
        )
        self.audit_repo.record(event)

        # Check stored raw record
        logs = self.audit_repo.list()
        self.assertEqual(len(logs), 1)
        self.assertNotIn(canary, logs[0].reason)
        self.assertIn("[REDACTED", logs[0].reason)


if __name__ == "__main__":
    unittest.main()
