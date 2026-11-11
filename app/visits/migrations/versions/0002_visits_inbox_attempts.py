"""visits.inbox: attempts, last_error; processed_at nullable (contract DL-31).

The Visits consumer counts failures of other causes in the inbox row, so a row can exist before
the reply is processed; processed_at, NULL until then, becomes the processed marker.

Revision ID: visits_0002
Revises: visits_0001
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "visits_0002"
down_revision: str | None = "visits_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "visits"
TIMESTAMPTZ = postgresql.TIMESTAMP(timezone=True)


def upgrade() -> None:
    op.add_column(
        "inbox",
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        schema=SCHEMA,
    )
    op.add_column("inbox", sa.Column("last_error", sa.Text(), nullable=True), schema=SCHEMA)
    op.alter_column(
        "inbox", "processed_at", schema=SCHEMA, existing_type=TIMESTAMPTZ, nullable=True, server_default=None
    )


def downgrade() -> None:
    # Rows of replies that never succeeded become processed in the M02 shape, which had no
    # other state; their failure history is dropped with the columns.
    op.execute(f"UPDATE {SCHEMA}.inbox SET processed_at = now() WHERE processed_at IS NULL")
    op.alter_column(
        "inbox",
        "processed_at",
        schema=SCHEMA,
        existing_type=TIMESTAMPTZ,
        nullable=False,
        server_default=sa.func.now(),
    )
    op.drop_column("inbox", "last_error", schema=SCHEMA)
    op.drop_column("inbox", "attempts", schema=SCHEMA)
