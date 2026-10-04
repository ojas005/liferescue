"""Raw DDL shared by Alembic and metadata.create_all (tests): audit_log append-only enforcement.

Layers (T/A items; contract checklist #8): (1) BEFORE UPDATE/DELETE row trigger and BEFORE TRUNCATE statement trigger
raise; (2) the migration grants the least-privilege app role only SELECT+INSERT on audit_log (see GRANTS)."""

from __future__ import annotations

POSTGRES_AUDIT_APPEND_ONLY = [
    """
    CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'audit_log is append-only (% blocked)', TG_OP USING ERRCODE = '42501';
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()
    """,
    """
    CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only()
    """,
]

SQLITE_AUDIT_APPEND_ONLY = [
    """
    CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END
    """,
    """
    CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END
    """,
]

POSTGRES_AUDIT_DROP = [
    "DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log",
    "DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log",
    "DROP FUNCTION IF EXISTS audit_log_append_only()",
]

# Least-privilege application role (A6): created by apps/api/docker/initdb for local dev; in other environments the
# operator creates it. Granted only when the role exists, so the migration also runs for a plain owner login.
APP_ROLE = "liferescue_app"
POSTGRES_GRANTS = f"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
    GRANT USAGE ON SCHEMA public TO {APP_ROLE};
    GRANT SELECT, INSERT, UPDATE, DELETE ON runs, approvals TO {APP_ROLE};
    GRANT SELECT, INSERT, DELETE ON run_events, evidence TO {APP_ROLE};  -- no UPDATE: timeline/evidence are write-once
    GRANT SELECT, INSERT ON audit_log TO {APP_ROLE};
    GRANT USAGE, SELECT ON SEQUENCE audit_log_seq_seq TO {APP_ROLE};
  END IF;
END $$
"""  # noqa: S608 - APP_ROLE is a module constant, not input
