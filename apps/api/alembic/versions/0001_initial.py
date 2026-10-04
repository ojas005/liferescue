"""initial schema: runs, run_events, approvals, evidence, audit_log (+ append-only guards, least-privilege grants)

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.ddl import (
    POSTGRES_AUDIT_APPEND_ONLY,
    POSTGRES_AUDIT_DROP,
    POSTGRES_GRANTS,
    SQLITE_AUDIT_APPEND_ONLY,
)

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSONT = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
TS = sa.DateTime(timezone=True)

RUN_STATES = ("intent", "evidence", "research", "plan", "policy", "approval", "action", "verification", "audit",
              "completed", "failed", "denied", "cancelled")
EVENT_TYPES = ("intent", "evidence", "research", "plan", "policy", "approval", "action", "verification", "audit",
               "state_change", "error")
APPROVAL_STATUSES = ("pending", "approved", "denied", "expired", "consumed", "revoked")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workflow_id", sa.String(64), nullable=False),
        sa.Column("workflow_version", sa.String(32), nullable=False),
        sa.Column("contract_version", sa.String(16), nullable=False),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("record", JSONT, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint(_in("state", RUN_STATES), name="ck_runs_state"),
    )
    op.create_index("ix_runs_workflow_id", "runs", ["workflow_id"])
    op.create_index("ix_runs_owner", "runs", ["owner"])
    op.create_index("ix_runs_state", "runs", ["state"])

    op.create_table(
        "run_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("ts", TS, nullable=False),
        sa.Column("step", sa.String(16), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("payload", JSONT, nullable=False),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
        sa.CheckConstraint(_in("step", RUN_STATES), name="ck_run_events_step"),
        sa.CheckConstraint(_in("type", EVENT_TYPES), name="ck_run_events_type"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.String(64), nullable=False),
        sa.Column("bound_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("risk", sa.String(16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("requested_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("decided_by", sa.String(128), nullable=True),
        sa.Column("decided_at", TS, nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.CheckConstraint(_in("status", APPROVAL_STATUSES), name="ck_approvals_status"),
    )
    op.create_index("ix_approvals_run_id", "approvals", ["run_id"])
    op.create_index("ix_approvals_status", "approvals", ["status"])

    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("content", JSONT, nullable=False),
        sa.Column("trust", sa.String(16), nullable=False),
        sa.Column("retrieved_at", TS, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
    )
    op.create_index("ix_evidence_run_id", "evidence", ["run_id"])

    op.create_table(
        "audit_log",
        sa.Column("seq", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("ts", TS, nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", JSONT, nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False, unique=True),
    )
    op.create_index("ix_audit_log_run_id", "audit_log", ["run_id"])

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for stmt in POSTGRES_AUDIT_APPEND_ONLY:
            op.execute(stmt)
        op.execute(POSTGRES_GRANTS)
    elif dialect == "sqlite":
        for stmt in SQLITE_AUDIT_APPEND_ONLY:
            op.execute(stmt)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for stmt in POSTGRES_AUDIT_DROP:
            op.execute(stmt)
    op.drop_table("audit_log")
    op.drop_table("evidence")
    op.drop_table("approvals")
    op.drop_table("run_events")
    op.drop_table("runs")
