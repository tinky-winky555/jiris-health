"""Completion logic (TDD section 6.2) and visit transitions (TDD section 6).

Every state change is a conditional UPDATE: PostgreSQL row locking lets one
transaction match the predicate, so concurrent requests serialise on the row.
Every transition also requires `completion_requested_at IS NULL`, so a visit
with a pending completion cannot be started, canceled or marked missed (R2,
contract DL-11). `apply_billing_reply` applies a Billing reply (TDD section 6.4,
contract DL-29 to DL-31).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts import (
    VISIT_COMPLETED,
    BillingFailed,
    BillingRecordCreated,
    Envelope,
    VisitCompleted,
    new_envelope,
)
from app.visits.models import (
    STATUS_CANCELED,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_MISSED,
    STATUS_SCHEDULED,
    Inbox,
    Outbox,
    Visit,
)

logger = logging.getLogger(__name__)

COMPLETABLE = (STATUS_SCHEDULED, STATUS_IN_PROGRESS)  # D10
CANCELABLE = (STATUS_SCHEDULED, STATUS_IN_PROGRESS)  # TDD section 6 state machine

REASON_PENDING = "completion_pending"
REASON_INVALID_STATUS = "invalid_status"


class VisitNotFound(Exception):
    pass


class VisitConflict(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class NewVisit:
    start_date_time: datetime
    end_date_time: datetime
    description: str
    rate: Decimal


def is_completion_pending(visit: Visit) -> bool:
    """TDD section 5.2: the field is kept after Completed (D23), hence the status clause."""
    return visit.completion_requested_at is not None and visit.status != STATUS_COMPLETED


async def create_visit(session: AsyncSession, data: NewVisit) -> Visit:
    visit = Visit(
        id=uuid.uuid7(),
        start_date_time=data.start_date_time,
        end_date_time=data.end_date_time,
        description=data.description,
        rate=data.rate,
        status=STATUS_SCHEDULED,
    )
    session.add(visit)
    await session.flush()
    return visit


async def get_visit(session: AsyncSession, visit_id: uuid.UUID) -> Visit:
    visit = await session.get(Visit, visit_id, populate_existing=True)
    if visit is None:
        raise VisitNotFound
    return visit


async def _conflict(session: AsyncSession, visit_id: uuid.UUID) -> VisitConflict:
    """Explain why a conditional UPDATE matched no row (TDD section 6.2, step 2)."""
    visit = await get_visit(session, visit_id)
    return VisitConflict(REASON_PENDING if is_completion_pending(visit) else REASON_INVALID_STATUS)


async def _conditional_update(
    session: AsyncSession,
    visit_id: uuid.UUID,
    allowed_from: tuple[str, ...],
    values: dict[str, Any],
) -> Visit:
    """UPDATE ... WHERE id AND status IN (...) AND completion_requested_at IS NULL RETURNING.

    For /complete this is the TDD section 6.2 statement with an equivalent predicate
    and SET; it returns the whole row (module-03 task 3.3).
    """
    statement = (
        update(Visit)
        .where(
            Visit.id == visit_id,
            Visit.status.in_(allowed_from),
            Visit.completion_requested_at.is_(None),
        )
        .values(**values)
        .returning(Visit)
        .execution_options(synchronize_session=False, populate_existing=True)
    )
    visit = (await session.execute(statement)).scalar_one_or_none()
    if visit is None:
        raise await _conflict(session, visit_id)
    return visit


async def request_completion(session: AsyncSession, visit_id: uuid.UUID) -> Visit:
    """Mark the visit pending and record VisitCompleted in the outbox, in the caller's
    transaction (FR1). The attempt id is the event id (R1)."""
    event_id = uuid.uuid7()
    visit = await _conditional_update(
        session,
        visit_id,
        COMPLETABLE,
        {
            "completion_requested_at": func.now(),
            "completion_attempt_id": event_id,
            "completion_failure_reason": None,
        },
    )
    envelope = new_envelope(
        VISIT_COMPLETED,
        VisitCompleted(
            visit_id=visit.id,
            completion_attempt_id=event_id,
            rate=visit.rate,
            start_date_time=visit.start_date_time,
            end_date_time=visit.end_date_time,
        ),
        event_id=event_id,
        occurred_at=visit.completion_requested_at,
    )
    session.add(
        Outbox(
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            schema_version=envelope.schema_version,
            payload=envelope.payload.model_dump(mode="json"),
            occurred_at=envelope.occurred_at,
        )
    )
    await session.flush()
    return visit


async def start_visit(session: AsyncSession, visit_id: uuid.UUID) -> Visit:
    return await _conditional_update(
        session, visit_id, (STATUS_SCHEDULED,), {"status": STATUS_IN_PROGRESS}
    )


async def cancel_visit(session: AsyncSession, visit_id: uuid.UUID) -> Visit:
    return await _conditional_update(session, visit_id, CANCELABLE, {"status": STATUS_CANCELED})


async def mark_missed(session: AsyncSession, visit_id: uuid.UUID) -> Visit:
    return await _conditional_update(
        session, visit_id, (STATUS_SCHEDULED,), {"status": STATUS_MISSED}
    )


# Billing replies (TDD section 6.4)


class UnknownVisit(Exception):
    """A reply names a visit that does not exist (contract DL-30)."""


@dataclass(frozen=True)
class ReplyOutcome:
    """completed, reset, noop (R3), ignored (R1) or duplicate."""

    kind: str
    visit_id: uuid.UUID


async def apply_billing_reply(
    session: AsyncSession, envelope: Envelope[BillingRecordCreated] | Envelope[BillingFailed]
) -> ReplyOutcome:
    """Apply one reply in the caller's transaction. The inbox row may already exist with
    failures counted (DL-31); processed_at marks a reply as processed."""
    payload = envelope.payload
    await session.execute(
        insert(Inbox)
        .values(event_id=envelope.event_id, event_type=envelope.event_type)
        .on_conflict_do_nothing(index_elements=[Inbox.event_id])
    )
    processed_at = (
        await session.execute(
            select(Inbox.processed_at).where(Inbox.event_id == envelope.event_id).with_for_update()
        )
    ).scalar_one()
    if processed_at is not None:
        return ReplyOutcome("duplicate", payload.visit_id)

    visit = (
        await session.execute(
            select(Visit)
            .where(Visit.id == payload.visit_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if visit is None:
        raise UnknownVisit(payload.visit_id)

    if visit.completion_attempt_id != payload.completion_attempt_id:
        kind = "ignored"  # R1: a reply for another attempt
    elif visit.status == STATUS_COMPLETED:
        # R3 for a second BillingRecordCreated. A BillingFailed for a Completed visit cannot
        # happen by design (one reply per attempt); resetting it would erase the history D23
        # keeps, so it is a no-op with a WARNING (approved by Sasha, TDD section 6.4).
        if isinstance(payload, BillingFailed):
            logger.warning(
                "BillingFailed ignored for a Completed visit visit_id=%s completion_attempt_id=%s"
                " event_id=%s",
                payload.visit_id,
                payload.completion_attempt_id,
                envelope.event_id,
            )
        kind = "noop"
    elif isinstance(payload, BillingRecordCreated):
        visit.status = STATUS_COMPLETED
        kind = "completed"
    else:
        visit.completion_requested_at = None  # D16: the visit can be completed again
        visit.completion_failure_reason = payload.reason
        kind = "reset"

    await session.execute(
        update(Inbox).where(Inbox.event_id == envelope.event_id).values(processed_at=func.now())
    )
    await session.flush()
    return ReplyOutcome(kind, payload.visit_id)
