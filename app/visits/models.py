"""SQLAlchemy models for schema "visits" (TDD section 5.1)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Index, MetaData, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "visits"

STATUS_SCHEDULED = "Scheduled"
STATUS_IN_PROGRESS = "In Progress"
STATUS_COMPLETED = "Completed"
STATUS_CANCELED = "Canceled"
STATUS_MISSED = "Missed"
STATUSES = (STATUS_SCHEDULED, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_CANCELED, STATUS_MISSED)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class Visit(Base):
    __tablename__ = "visit"
    __table_args__ = (
        CheckConstraint("end_date_time > start_date_time", name="ck_visit_time_range"),
        CheckConstraint("rate > 0", name="ck_visit_rate_positive"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{status}'" for status in STATUSES) + ")",
            name="ck_visit_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    start_date_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    end_date_time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    description: Mapped[str] = mapped_column(Text)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(Text)
    completion_requested_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completion_attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    completion_failure_reason: Mapped[str | None] = mapped_column(Text)


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
    """De-duplication and failure count of Billing replies (TDD sections 5.1 and 6.4; DL-31).

    processed_at is NULL until the reply is applied or ignored; a row with processed_at NULL
    holds the failures counted so far.
    """

    __tablename__ = "inbox"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
