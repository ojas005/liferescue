"""Alembic environment. URL precedence: -x url=... > sqlalchemy.url option > DATABASE_URL env/.env."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base
from app.settings import get_settings, normalize_database_url

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    x = context.get_x_argument(as_dictionary=True).get("url")
    return normalize_database_url(
        x or config.get_main_option("sqlalchemy.url") or get_settings().database_url
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
