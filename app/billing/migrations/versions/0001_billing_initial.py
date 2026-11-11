"""Schema billing: billing_record, outbox, inbox and grants for billing_app.

Revision ID: billing_0001
Revises:
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "billing_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "billing"
APP_ROLE = "billing_app"
TIMESTAMPTZ = postgresql.TIMESTAMP(timezone=True)


def upgrade() -> None:
    op.create_table(
        "billing_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('Created', 'Reversed')", name="ck_billing_record_status"),
        schema=SCHEMA,
    )
    # One active record per visit (D3, D12).
    op.create_index(
        "ux_active_record",
        "billing_record",
        ["visit_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'Created'"),
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
        sa.Column("status", sa.Text(), server_default=sa.text("'processing'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", TIMESTAMPTZ, nullable=True),
        sa.CheckConstraint(
            "status IN ('processing', 'processed', 'failed')", name="ck_inbox_status"
        ),
        schema=SCHEMA,
    )

    # TDD section 9: the application role gets DML on its own schema only (D29).
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.billing_record, {SCHEMA}.outbox, "
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
    op.drop_index("ux_active_record", table_name="billing_record", schema=SCHEMA)
    op.drop_table("billing_record", schema=SCHEMA)
    op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM {APP_ROLE}")
