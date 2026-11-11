"""Consumer of visits.* events from queue billing.inbox (TDD section 8.2; D15; contract DL-25,
DL-35, DL-36).

Built on the shared mechanics of app/outbox/consumer.py (DL-33): manual acknowledgement, raw
body, one log line per message. One transaction per message, ack only after COMMIT:

- not a valid VisitCompleted envelope (R9): reject without requeue, to billing.parking;
- processed, or a duplicate (inbox `processed` or `failed`): ack;
- database unavailable or connection lost: nack with requeue after a backoff of 0.5 s
  doubling to 30 s, without a limit and never counted (D6, DL-35);
- permanent (payload validation, SQLSTATE classes 22 and 23 except 23505): a short
  transaction sets the inbox row `failed` and writes BillingFailed `permanent`; ack (DL-36);
- transient or unclassified: a short transaction adds 1 to `attempts`; below 5, nack with
  requeue after 1 s; at 5, inbox `failed`, BillingFailed `transient_exhausted`, reject to
  billing.parking (D15).

A failure of the short transaction itself is classified again: unavailable backs off; any
other cause requeues after 1 s without counting. The queue object comes from
app/outbox/topology.py; this module declares and binds nothing.
"""

import asyncio
import logging
from collections.abc import Iterator
from typing import Literal

from faststream.rabbit import RabbitBroker
from faststream.rabbit.annotations import RabbitMessage
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.service import (
    PermanentError,
    count_transient_failure,
    process_visit_completed,
    record_permanent_failure,
)
from app.contracts import VISIT_COMPLETED, Envelope, VisitCompleted
from app.outbox import consumer as mechanics
from app.outbox.consumer import MalformedMessage
from app.outbox.relay import BACKOFF_CEILING_S, POLL_INTERVAL_S, backoff_delays
from app.outbox.topology import BILLING_INBOX, INBOX_QUEUES

logger = logging.getLogger(__name__)

MODULE = "billing"
REQUEUE_DELAY_S = 1.0  # D28: short delay before a requeue
UNIQUE_VIOLATION = "23505"  # stays transient (DL-36): a concurrent duplicate resolves on retry
PERMANENT_SQLSTATE_CLASSES = ("22", "23")  # data exception, integrity constraint violation

ErrorClass = Literal["unavailable", "permanent", "transient"]

__all__ = ["MalformedMessage", "classify", "parse_visit_completed", "register"]


def parse_visit_completed(body: bytes) -> Envelope[VisitCompleted]:
    try:
        envelope = Envelope[VisitCompleted].model_validate_json(body)
    except ValidationError as error:
        raise MalformedMessage(str(error).splitlines()[0]) from error
    if envelope.event_type != VISIT_COMPLETED.event_type:
        raise MalformedMessage(f"unexpected event_type {envelope.event_type!r}")
    if envelope.schema_version != VISIT_COMPLETED.schema_version:
        raise MalformedMessage(f"unsupported schema_version {envelope.schema_version}")
    return envelope


def classify(error: BaseException) -> ErrorClass:
    """Error class of a failed VisitCompleted (D15 as refined by DL-35 and DL-36)."""
    chain = list(mechanics.error_chain(error))
    if any(isinstance(current, PermanentError) for current in chain):
        return "permanent"
    if mechanics.is_database_unavailable(error):
        return "unavailable"
    for current in chain:
        sqlstate = getattr(current, "sqlstate", None)
        if isinstance(sqlstate, str) and sqlstate:
            if sqlstate == UNIQUE_VIOLATION:
                return "transient"
            if sqlstate[:2] in PERMANENT_SQLSTATE_CLASSES:
                return "permanent"
            return "transient"
    return "transient"  # unclassified errors count as transient (D15)


class BillingConsumer:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._backoff: Iterator[float] | None = None  # while the database is unavailable

    async def handle(self, message: RabbitMessage) -> None:
        try:
            envelope = parse_visit_completed(message.body)
        except MalformedMessage as error:
            await message.reject(requeue=False)
            self._log(logging.ERROR, message, "parked", error=error)
            return
        try:
            async with self._sessions.begin() as session:
                outcome = await process_visit_completed(session, envelope)
        except Exception as error:
            await self._failed(message, envelope, error)
            return
        self._backoff = None
        await message.ack()  # after COMMIT
        self._log(logging.INFO, message, "duplicate" if outcome.duplicate else "processed", envelope)

    async def _failed(
        self, message: RabbitMessage, envelope: Envelope[VisitCompleted], error: Exception
    ) -> None:
        error_class = classify(error)
        if error_class == "unavailable":
            await self._back_off(message, envelope, error)
            return
        try:
            async with self._sessions.begin() as session:
                if error_class == "permanent":
                    reply = await record_permanent_failure(session, envelope, error)
                else:
                    count = await count_transient_failure(session, envelope, error)
        except Exception as record_error:  # the short transaction failed as well
            if classify(record_error) == "unavailable":
                await self._back_off(message, envelope, record_error)
            else:
                self._log(logging.ERROR, message, "requeued", envelope, " cause=uncounted", record_error)
                await asyncio.sleep(REQUEUE_DELAY_S)
                await message.nack(requeue=True)
            return
        self._backoff = None
        if error_class == "permanent":
            await message.ack()  # after COMMIT of BillingFailed; never parked (TDD section 8.2)
            outcome = "failed" if reply else "duplicate"
            self._log(logging.ERROR, message, outcome, envelope, " error_class=permanent", error)
        elif count.settled:
            await message.ack()
            self._log(logging.INFO, message, "duplicate", envelope)
        elif count.exhausted:
            await message.reject(requeue=False)  # after COMMIT of BillingFailed
            details = f" attempts={count.attempts} error_class=transient_exhausted"
            self._log(logging.ERROR, message, "parked", envelope, details, error)
        else:
            details = f" attempts={count.attempts} cause=transient"
            self._log(logging.ERROR, message, "requeued", envelope, details, error)
            await asyncio.sleep(REQUEUE_DELAY_S)
            await message.nack(requeue=True)

    async def _back_off(
        self, message: RabbitMessage, envelope: Envelope[VisitCompleted], error: Exception
    ) -> None:
        self._backoff = self._backoff or backoff_delays(POLL_INTERVAL_S, BACKOFF_CEILING_S)
        delay = next(self._backoff)
        details = f" cause=database_unavailable delay={delay}"
        self._log(logging.WARNING, message, "requeued", envelope, details, error)
        await asyncio.sleep(delay)
        await message.nack(requeue=True)

    def _log(
        self,
        level: int,
        message: RabbitMessage,
        outcome: str,
        envelope: Envelope[VisitCompleted] | None = None,
        details: str = "",
        error: BaseException | None = None,
    ) -> None:
        mechanics.log_consumed(
            logger,
            level,
            MODULE,
            message,
            outcome,
            event_id=envelope.event_id if envelope else "-",
            event_type=envelope.event_type if envelope else "-",
            visit_id=envelope.payload.visit_id if envelope else "-",
            details=details,
            error=error,
        )


def register(broker: RabbitBroker, sessions: async_sessionmaker[AsyncSession]) -> None:
    """Subscribe the Billing handler to billing.inbox on `broker` (module-05 section 3)."""
    mechanics.subscribe(broker, INBOX_QUEUES[BILLING_INBOX], BillingConsumer(sessions).handle)
