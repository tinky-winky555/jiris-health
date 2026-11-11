"""Amount calculation and record creation for one VisitCompleted (TDD section 8.2; D3, D11, R8).

`process_visit_completed` runs inside the caller's transaction: the inbox row, the billing
record and the BillingRecordCreated reply are committed together or not at all. Error
classification (permanent, counted transient) arrives with M07.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import (
    INBOX_PROCESSED,
    INBOX_PROCESSING,
    RECORD_CREATED,
    BillingRecord,
    Inbox,
    Outbox,
)
from app.contracts import (
    BILLING_RECORD_CREATED,
    BillingRecordCreated,
    Envelope,
    VisitCompleted,
    new_envelope,
    to_money,
)

MICROSECONDS_PER_HOUR = Decimal(3_600_000_000)
ACTIVE_RECORD_PREDICATE = text(f"status = '{RECORD_CREATED}'")


def compute_amount(rate: Decimal, start: datetime, end: datetime) -> Decimal:
    """rate x hours(end - start), from the exact duration in microseconds, 2 places, HALF_UP."""
    if not isinstance(rate, Decimal):
        raise TypeError("rate must be a Decimal")
    duration = end - start
    microseconds = (duration.days * 86_400 + duration.seconds) * 1_000_000 + duration.microseconds
    return to_money(rate * Decimal(microseconds) / MICROSECONDS_PER_HOUR)


@dataclass(frozen=True)
class BillingOutcome:
    duplicate: bool
    billing_record_id: uuid.UUID | None = None
    reply_event_id: uuid.UUID | None = None
    amount: Decimal | None = None


async def process_visit_completed(
    session: AsyncSession, envelope: Envelope[VisitCompleted]
) -> BillingOutcome:
    payload = envelope.payload

    # De-duplication: the second delivery of an event waits here for the first
    # transaction, then finds its row (TDD section 8.2).
    await session.execute(
        insert(Inbox)
        .values(event_id=envelope.event_id, event_type=envelope.event_type, status=INBOX_PROCESSING)
        .on_conflict_do_nothing(index_elements=[Inbox.event_id])
    )
    status = (
        await session.execute(
            select(Inbox.status).where(Inbox.event_id == envelope.event_id).with_for_update()
        )
    ).scalar_one()
    if status != INBOX_PROCESSING:
        return BillingOutcome(duplicate=True)

    # One active record per visit (D3): the partial unique index decides, never a read first.
    amount = compute_amount(payload.rate, payload.start_date_time, payload.end_date_time)
    record_id = (
        await session.execute(
            insert(BillingRecord)
            .values(id=uuid.uuid7(), visit_id=payload.visit_id, amount=amount, status=RECORD_CREATED)
            .on_conflict_do_nothing(
                index_elements=[BillingRecord.visit_id],
                # A literal, exactly as in ux_active_record, never a bound parameter: asyncpg
                # prepares the statement, and once PostgreSQL switches it to a generic plan
                # (after five executions, or at once under plan_cache_mode =
                # force_generic_plan) a parameter cannot prove the partial index predicate, so
                # the INSERT fails with "no unique or exclusion constraint matching the ON
                # CONFLICT specification". See TDD section 8.2; regression test
                # test_on_conflict_survives_the_generic_plan.
                index_where=ACTIVE_RECORD_PREDICATE,
            )
            .returning(BillingRecord.id)
        )
    ).scalar_one_or_none()
    if record_id is None:
        # R8: an active record exists; reply with it, so the visit still completes.
        record_id, amount = (
            await session.execute(
                select(BillingRecord.id, BillingRecord.amount).where(
                    BillingRecord.visit_id == payload.visit_id,
                    BillingRecord.status == RECORD_CREATED,
                )
            )
        ).one()

    reply = new_envelope(
        BILLING_RECORD_CREATED,
        BillingRecordCreated(
            visit_id=payload.visit_id,
            completion_attempt_id=payload.completion_attempt_id,
            billing_record_id=record_id,
            amount=amount,
        ),
    )
    session.add(
        Outbox(
            event_id=reply.event_id,
            event_type=reply.event_type,
            schema_version=reply.schema_version,
            payload=reply.payload.model_dump(mode="json"),
            occurred_at=reply.occurred_at,
        )
    )
    await session.execute(
        update(Inbox)
        .where(Inbox.event_id == envelope.event_id)
        .values(status=INBOX_PROCESSED, processed_at=func.now())
    )
    await session.flush()
    return BillingOutcome(
        duplicate=False, billing_record_id=record_id, reply_event_id=reply.event_id, amount=amount
    )
