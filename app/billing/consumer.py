"""Consumer of visits.* events from queue billing.inbox (TDD section 8.2; contract DL-25).

Every message is settled here, never by FastStream (`AckPolicy.MANUAL`): its default,
reject on error, would park a VisitCompleted on any exception and leave the visit pending
(D6). One message at a time, one transaction per message, ack only after COMMIT:

- not a valid VisitCompleted envelope (R9): reject without requeue, to billing.parking;
- processed, or a duplicate: ack;
- any other exception, interim until M07: ROLLBACK, ERROR line, nack with requeue after 1 s.

The queue object comes from app/outbox/topology.py; this module declares and binds nothing.
"""

import asyncio
import logging
from typing import Any

from faststream import AckPolicy
from faststream.message import StreamMessage
from faststream.rabbit import RabbitBroker
from faststream.rabbit.annotations import RabbitMessage
from faststream.rabbit.schemas import Channel
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.service import process_visit_completed
from app.contracts import VISIT_COMPLETED, Envelope, VisitCompleted
from app.outbox.topology import BILLING_INBOX, INBOX_QUEUES

logger = logging.getLogger(__name__)

REQUEUE_DELAY_S = 1.0  # D28: short delay before a requeue
PREFETCH = 10


class MalformedMessage(Exception):
    """The body is not a VisitCompleted envelope of schema version 1 (R9)."""


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


def _log(
    level: int,
    message: RabbitMessage,
    outcome: str,
    envelope: Envelope[VisitCompleted] | None = None,
    error: BaseException | None = None,
) -> None:
    logger.log(
        level,
        "event consumed module=billing event_id=%s event_type=%s visit_id=%s message_id=%s"
        " redelivered=%s outcome=%s%s",
        envelope.event_id if envelope else "-",
        envelope.event_type if envelope else "-",
        envelope.payload.visit_id if envelope else "-",
        message.message_id or "-",
        message.raw_message.redelivered,
        outcome,
        f" error={error!r}" if error else "",
    )


async def handle(message: RabbitMessage, sessions: async_sessionmaker[AsyncSession]) -> None:
    try:
        envelope = parse_visit_completed(message.body)
    except MalformedMessage as error:
        await message.reject(requeue=False)
        _log(logging.ERROR, message, "parked", error=error)
        return
    try:
        async with sessions.begin() as session:
            outcome = await process_visit_completed(session, envelope)
    except Exception as error:  # interim until M07: never lose the event (D6)
        _log(logging.ERROR, message, "requeued", envelope, error)
        await asyncio.sleep(REQUEUE_DELAY_S)
        await message.nack(requeue=True)
        return
    await message.ack()  # after COMMIT
    _log(logging.INFO, message, "duplicate" if outcome.duplicate else "processed", envelope)


async def _raw_body(message: StreamMessage[Any]) -> bytes:
    """Hand the body over undecoded. FastStream's JSON decoder would fail on a malformed
    body before the handler runs, and under AckPolicy.MANUAL that message would stay
    unsettled for ever; parsing belongs to `parse_visit_completed` (DL-25)."""
    return message.body


def register(broker: RabbitBroker, sessions: async_sessionmaker[AsyncSession]) -> None:
    """Subscribe the Billing handler to billing.inbox on `broker` (module-05 section 3)."""

    @broker.subscriber(
        INBOX_QUEUES[BILLING_INBOX],
        ack_policy=AckPolicy.MANUAL,
        channel=Channel(prefetch_count=PREFETCH),
        decoder=_raw_body,
    )
    async def on_billing_inbox(message: RabbitMessage) -> None:
        await handle(message, sessions)
