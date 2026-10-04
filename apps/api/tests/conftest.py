"""Fixtures.

Default: in-memory SQLite (no external services). If DATABASE_URL points at PostgreSQL the same tests run against it: the
schema is built by the real Alembic migration and every table is truncated (audit_log via its owner, triggers permitting)
between tests. Safety: a PostgreSQL database is touched only if its name contains "test" (API_TESTS_ALLOW_ANY_DB=1 overrides).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from contract.fakes import MockModel
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import make_engine, make_sessionmaker
from app.main import create_app
from app.settings import Settings, normalize_database_url
from tests.dev_stack import fake_engine_factory

API_DIR = Path(__file__).resolve().parents[1]


def _pg_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url and normalize_database_url(url).startswith("postgresql"):
        return normalize_database_url(url)
    return None


PG_URL = _pg_url()
USING_PG = PG_URL is not None


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine | None]:
    if PG_URL is None:
        yield None
        return
    name = make_url(PG_URL).database or ""
    if "test" not in name and os.environ.get("API_TESTS_ALLOW_ANY_DB") != "1":
        pytest.exit(
            f"refusing to run tests against database {name!r}: name must contain 'test'", returncode=2
        )
    engine = make_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(PG_URL), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def engine(pg_engine: Engine | None) -> Iterator[Engine]:
    if pg_engine is not None:
        names = ", ".join(t.name for t in Base.metadata.sorted_tables if t.name != "audit_log")
        with pg_engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
            # audit_log is append-only incl. TRUNCATE: tests (owner only) lift the guard to reset, then restore it.
            conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER USER"))
            conn.execute(text("TRUNCATE audit_log RESTART IDENTITY"))
            conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER USER"))
        yield pg_engine
    else:
        eng = make_engine("sqlite://")
        Base.metadata.create_all(eng)
        yield eng
        eng.dispose()


@pytest.fixture
def sf(engine: Engine) -> sessionmaker[Session]:
    return make_sessionmaker(engine)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None, liferescue_env="test", model_adapter="mock", database_url=PG_URL or "sqlite://"
    )


@pytest.fixture
def client(engine: Engine, settings: Settings) -> Iterator[TestClient]:
    """Runtime NOT wired (no app.runtime.wiring): placeholder engine that creates runs but does not advance them."""
    yield TestClient(
        create_app(settings, db_engine=engine)
    )  # no `with`: lifespan would dispose the shared engine


@pytest.fixture
def make_slice_client(engine: Engine, settings: Settings) -> Callable[..., TestClient]:
    def make(model: MockModel | None = None, settings_override: Settings | None = None) -> TestClient:
        app = create_app(
            settings_override or settings, db_engine=engine, run_engine_factory=fake_engine_factory(model)
        )
        return TestClient(app)

    return make


@pytest.fixture
def slice_client(make_slice_client: Callable[..., TestClient]) -> TestClient:
    """Full pipeline: contract ReferenceRunEngine + fakes over the real SQL store/audit/approvals/policy."""
    return make_slice_client()


VEHICLE = {
    "workflow_id": "vehicle_breakdown",
    "input": {"description": "Car overheated on highway", "location": "NH48 Pune", "vehicle": "i20"},
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
