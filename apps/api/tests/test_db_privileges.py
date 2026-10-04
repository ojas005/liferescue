"""Schema checks: migration == models, offline PostgreSQL DDL, and least-privilege role (needs real PostgreSQL)."""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.base import Base
from tests.conftest import PG_URL, USING_PG, alembic_config


def test_migration_matches_models_on_sqlite(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    command.upgrade(alembic_config(url), "head")
    eng = create_engine(url)
    with eng.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    command.downgrade(alembic_config(url), "base")
    eng.dispose()


def test_offline_sql_for_postgresql_is_generated(capsys: pytest.CaptureFixture[str]) -> None:
    command.upgrade(alembic_config("postgresql+psycopg://u:p@localhost/x"), "head", sql=True)
    sql = capsys.readouterr().out
    for t in ("runs", "run_events", "approvals", "evidence", "audit_log"):
        assert f"CREATE TABLE {t}" in sql
    assert "JSONB" in sql and "UUID" in sql and "TIMESTAMP WITH TIME ZONE" in sql
    assert (
        "audit_log_append_only" in sql
        and "BEFORE TRUNCATE" in sql
        and "GRANT SELECT, INSERT ON audit_log" in sql
    )


def test_constraints_reject_bad_enum_values(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO runs (id, workflow_id, workflow_version, contract_version, owner, state, version, record, created_at, updated_at) "
                "VALUES ('00000000-0000-0000-0000-000000000001','w','0.1.0','0.1.0','o','exploded',0,'{}','2026-01-01','2026-01-01')"
            )
        )


@pytest.mark.postgres
def test_postgres_schema_matches_models(pg_engine: Engine | None) -> None:
    if pg_engine is None:
        pytest.skip("DATABASE_URL does not point at PostgreSQL")
    with pg_engine.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001"
        jsonb = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND data_type='jsonb'"
            )
        ).scalar_one()
    assert jsonb == 4  # runs.record, run_events.payload, evidence.content, audit_log.payload


@pytest.mark.postgres
def test_app_role_cannot_update_or_delete_audit_log(pg_engine: Engine | None) -> None:
    """Privilege layer (independent of the trigger): liferescue_app has SELECT+INSERT only on audit_log."""
    if PG_URL is None or pg_engine is None:
        pytest.skip("needs PostgreSQL")
    with pg_engine.connect() as c:
        if not c.execute(text("SELECT 1 FROM pg_roles WHERE rolname='liferescue_app'")).first():
            pytest.skip("role liferescue_app not present (create it via apps/api/docker/initdb)")
    app_url = make_url(PG_URL).set(username="liferescue_app", password="liferescue_app_dev")
    app_engine = create_engine(app_url)
    try:
        with app_engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO audit_log (seq, ts, run_id, actor, event_type, payload, prev_hash, hash) "
                    "VALUES (900001, now(), 'r', 'a', 'e', '{}', '', 'h-900001')"
                )
            )
        for stmt in ("UPDATE audit_log SET actor='x'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
            with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as c:
                c.execute(text(stmt))
        with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as c:
            c.execute(
                text("UPDATE run_events SET seq = seq")
            )  # timeline is write-once for the app role as well
        with pytest.raises(DBAPIError, match="permission denied"), app_engine.begin() as c:
            c.execute(text("CREATE TABLE evil (x int)"))  # not an owner / no DDL
    finally:
        app_engine.dispose()


def test_using_pg_flag_is_consistent() -> None:
    assert (PG_URL is not None) == USING_PG
