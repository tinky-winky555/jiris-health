"""Amount calculation and record creation for one VisitCompleted (TDD section 8.2; D3, D11, R8).

`process_visit_completed` runs inside the caller's transaction: the inbox row, the billing
record and the BillingRecordCreated reply are committed together or not at all. After a
failure the consumer calls `record_permanent_failure` or `count_transient_failure` in a new,
short transaction (TDD section 8.2; D15; contract DL-35, DL-36).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import (
    INBOX_FAILED,
    INBOX_PROCESSED,
    INBOX_PROCESSING,
    RECORD_CREATED,
    BillingRecord,
    Inbox,
    Outbox,
)
from app.contracts import (
    BILLING_FAILED,
    BILLING_RECORD_CREATED,
    BillingFailed,
    BillingRecordCreated,
    Envelope,
    VisitCompleted,
    new_envelope,
    to_money,
)
from app.outbox.consumer import error_chain

MICROSECONDS_PER_HOUR = Decimal(3_600_000_000)
ACTIVE_RECORD_PREDICATE = text(f"status = '{RECORD_CREATED}'")


TRANSIENT_ATTEMPT_LIMIT = 5  # D15
REASON_MAX = 500
LAST_ERROR_MAX = 2000


class PermanentError(Exception):
    """The payload cannot be billed, whatever the number of retries (D15)."""


def compute_amount(rate: Decimal, start: datetime, end: datetime) -> Decimal:
    """rate x hours(end - start), from the exact duration in microseconds, 2 places, HALF_UP."""
    if not isinstance(rate, Decimal):
        raise TypeError("rate must be a Decimal")
    if rate <= 0:
        raise PermanentError(f"non-positive rate {rate}")
    duration = end - start
    if duration.total_seconds() <= 0:
        raise PermanentError(f"non-positive duration {duration}")
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


# Failure paths (TDD section 8.2): each runs in its own short transaction after the ROLLBACK


# Stable codes for BillingFailed.reason (TD-7, TDD section 7): API clients see these and
# nothing else; the raw exception text stays in billing.inbox.last_error.
REASON_INVALID_PAYLOAD = "invalid_payload"
REASON_AMOUNT_OUT_OF_RANGE = "amount_out_of_range"
REASON_INVALID_DATA = "invalid_data"
REASON_CONSTRAINT_VIOLATION = "constraint_violation"
REASON_TRANSIENT_EXHAUSTED = "transient_errors_exhausted"
REASON_CODES = frozenset(
    {
        REASON_INVALID_PAYLOAD,
        REASON_AMOUNT_OUT_OF_RANGE,
        REASON_INVALID_DATA,
        REASON_CONSTRAINT_VIOLATION,
        REASON_TRANSIENT_EXHAUSTED,
    }
)


def failure_reason(error: BaseException, error_class: str) -> str:
    """The stable code of a failure (TD-7)."""
    if error_class == "transient_exhausted":
        return REASON_TRANSIENT_EXHAUSTED
    for current in error_chain(error):
        if isinstance(current, PermanentError):
            return REASON_INVALID_PAYLOAD
        sqlstate = getattr(current, "sqlstate", None)
        if isinstance(sqlstate, str) and sqlstate:
            if sqlstate == "22003":
                return REASON_AMOUNT_OUT_OF_RANGE
            if sqlstate[:2] == "22":
                return REASON_INVALID_DATA
            if sqlstate[:2] == "23":
                return REASON_CONSTRAINT_VIOLATION
    return REASON_INVALID_PAYLOAD


def describe(error: BaseException) -> str:
    """Type and first line of the message, for billing.inbox.last_error only; never the
    payload, never sent to Visits or to an API client (TD-7)."""
    first_line = str(error).strip().splitlines()[0] if str(error).strip() else ""
    return f"{type(error).__name__}: {first_line}"


def _billing_failed(
    envelope: Envelope[VisitCompleted], reason: str, error_class: str
) -> Outbox:
    """BillingFailed with a stable `reason` code (TD-7)."""
    if reason not in REASON_CODES:
        raise ValueError(f"not a reason code: {reason!r}")
    reply = new_envelope(
        BILLING_FAILED,
        BillingFailed(
            visit_id=envelope.payload.visit_id,
            completion_attempt_id=envelope.payload.completion_attempt_id,
            reason=reason[:REASON_MAX],
            error_class=error_class,
        ),
    )
    return Outbox(
        event_id=reply.event_id,
        event_type=reply.event_type,
        schema_version=reply.schema_version,
        payload=reply.payload.model_dump(mode="json"),
        occurred_at=reply.occurred_at,
    )


async def record_permanent_failure(
    session: AsyncSession, envelope: Envelope[VisitCompleted], error: BaseException
) -> uuid.UUID | None:
    """Inbox `failed` and one BillingFailed `permanent`; None if the event was settled
    meanwhile (processed or failed), so the reply is written at most once."""
    reason = describe(error)
    statement = insert(Inbox).values(
        event_id=envelope.event_id,
        event_type=envelope.event_type,
        status=INBOX_FAILED,
        last_error=reason[:LAST_ERROR_MAX],
        processed_at=func.now(),
    )
    settled = (
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[Inbox.event_id],
                set_={
                    "status": INBOX_FAILED,
                    "last_error": statement.excluded.last_error,
                    "processed_at": func.now(),
                },
                where=Inbox.status == INBOX_PROCESSING,
            ).returning(Inbox.event_id)
        )
    ).scalar_one_or_none()
    if settled is None:
        return None
    reply = _billing_failed(envelope, failure_reason(error, "permanent"), "permanent")
    session.add(reply)
    await session.flush()
    return reply.event_id


@dataclass(frozen=True)
class TransientCount:
    attempts: int
    exhausted: bool
    settled: bool = False  # the event was processed or failed meanwhile
    reply_event_id: uuid.UUID | None = None


async def count_transient_failure(
    session: AsyncSession,
    envelope: Envelope[VisitCompleted],
    error: BaseException,
    limit: int = TRANSIENT_ATTEMPT_LIMIT,
) -> TransientCount:
    """attempts + 1 and last_error; at `limit`, inbox `failed` and one BillingFailed
    `transient_exhausted` (D15). The counter survives restarts."""
    last_error = describe(error)
    statement = insert(Inbox).values(
        event_id=envelope.event_id,
        event_type=envelope.event_type,
        status=INBOX_PROCESSING,
        attempts=1,
        last_error=last_error[:LAST_ERROR_MAX],
    )
    attempts = (
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[Inbox.event_id],
                set_={"attempts": Inbox.attempts + 1, "last_error": statement.excluded.last_error},
                where=Inbox.status == INBOX_PROCESSING,
            ).returning(Inbox.attempts)
        )
    ).scalar_one_or_none()
    if attempts is None:
        return TransientCount(attempts=0, exhausted=False, settled=True)
    if attempts < limit:
        return TransientCount(attempts=attempts, exhausted=False)
    await session.execute(
        update(Inbox)
        .where(Inbox.event_id == envelope.event_id)
        .values(status=INBOX_FAILED, processed_at=func.now())
    )
    reply = _billing_failed(envelope, REASON_TRANSIENT_EXHAUSTED, "transient_exhausted")
    session.add(reply)
    await session.flush()
    return TransientCount(attempts=attempts, exhausted=True, reply_event_id=reply.event_id)
