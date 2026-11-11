"""SQLAlchemy models for schema "billing" (TDD section 5.2)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Index, MetaData, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "billing"

RECORD_CREATED = "Created"
RECORD_REVERSED = "Reversed"

INBOX_PROCESSING = "processing"
INBOX_PROCESSED = "processed"
INBOX_FAILED = "failed"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class BillingRecord(Base):
    __tablename__ = "billing_record"
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{RECORD_CREATED}', '{RECORD_REVERSED}')", name="ck_billing_record_status"
        ),
        # One active record per visit (D3, D12).
        Index(
            "ux_active_record",
            "visit_id",
            unique=True,
            postgresql_where=text(f"status = '{RECORD_CREATED}'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))  # no cross-schema FK
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        Index(
            "ix_outbox_unpublished",
            "occurred_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[int]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    attempts: Mapped[int] = mapped_column(server_default=text("0"))


class Inbox(Base):
    __tablename__ = "inbox"
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{INBOX_PROCESSING}', '{INBOX_PROCESSED}', '{INBOX_FAILED}')",
            name="ck_inbox_status",
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text(f"'{INBOX_PROCESSING}'"))
    attempts: Mapped[int] = mapped_column(server_default=text("0"))  # survives restarts (D15)
    last_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
