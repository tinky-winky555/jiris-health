"""Schema visits: visit, outbox, inbox and grants for visits_app.

Revision ID: visits_0001
Revises:
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "visits_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "visits"
APP_ROLE = "visits_app"
TIMESTAMPTZ = postgresql.TIMESTAMP(timezone=True)


def upgrade() -> None:
    op.create_table(
        "visit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("start_date_time", TIMESTAMPTZ, nullable=False),
        sa.Column("end_date_time", TIMESTAMPTZ, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rate", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("completion_requested_at", TIMESTAMPTZ, nullable=True),
        sa.Column("completion_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("completion_failure_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("end_date_time > start_date_time", name="ck_visit_time_range"),
        sa.CheckConstraint("rate > 0", name="ck_visit_rate_positive"),
        sa.CheckConstraint(
            "status IN ('Scheduled', 'In Progress', 'Completed', 'Canceled', 'Missed')",
            name="ck_visit_status",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "outbox",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", TIMESTAMPTZ, nullable=False),
        sa.Column("published_at", TIMESTAMPTZ, nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_outbox_unpublished",
        "outbox",
        ["occurred_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("published_at IS NULL"),
    )

    op.create_table(
        "inbox",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("processed_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )

    # TDD section 9: the application role gets DML on its own schema only (D29).
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.visit, {SCHEMA}.outbox, "
        f"{SCHEMA}.inbox TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
    )
    op.drop_table("inbox", schema=SCHEMA)
    op.drop_index("ix_outbox_unpublished", table_name="outbox", schema=SCHEMA)
    op.drop_table("outbox", schema=SCHEMA)
    op.drop_table("visit", schema=SCHEMA)
    op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM {APP_ROLE}")
