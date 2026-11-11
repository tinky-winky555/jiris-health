"""Completion logic (TDD section 6.2) and visit transitions (TDD section 6).

Every state change is a conditional UPDATE: PostgreSQL row locking lets one
transaction match the predicate, so concurrent requests serialise on the row.
Every transition also requires `completion_requested_at IS NULL`, so a visit
with a pending completion cannot be started, canceled or marked missed (R2,
contract DL-11). Billing reply handlers (TDD section 6.4) arrive with M06.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts import VISIT_COMPLETED, VisitCompleted, new_envelope
from app.visits.models import (
    STATUS_CANCELED,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_MISSED,
    STATUS_SCHEDULED,
    Outbox,
    Visit,
)

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
