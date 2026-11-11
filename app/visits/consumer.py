"""Consumer of billing.* events from queue visits.inbox (TDD section 6.4; contract DL-29 to
DL-31, DL-33).

Built on app/outbox/consumer.py: manual acknowledgement, raw body, one log line per message.
One transaction per message, ack only after COMMIT. Failure classes, as in the relay:

- not a BillingRecordCreated or BillingFailed envelope of schema version 1 with a valid
  payload (R9), or a reply for a visit that does not exist (DL-30): reject without requeue,
  to visits.parking, with an ERROR line;
- database unavailable or connection lost: nack with requeue after an exponential backoff
  (0.5 s doubling to 30 s), without a limit and without counting (D6);
- any other exception: ROLLBACK, then a short transaction adds 1 to `attempts` and stores
  `last_error` in visits.inbox; below 5, nack with requeue after 1 s; at 5, reject to
  visits.parking with an ERROR line.

The queue object comes from app/outbox/topology.py; this module declares and binds nothing.
"""

import asyncio
import json
import logging
from collections.abc import Iterator

from faststream.rabbit import RabbitBroker
from faststream.rabbit.annotations import RabbitMessage
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts import (
    BILLING_FAILED,
    BILLING_RECORD_CREATED,
    BillingFailed,
    BillingRecordCreated,
    Envelope,
)
from app.outbox import consumer as mechanics
from app.outbox.consumer import MalformedMessage
from app.outbox.relay import BACKOFF_CEILING_S, POLL_INTERVAL_S, backoff_delays
from app.outbox.topology import INBOX_QUEUES, VISITS_INBOX
from app.visits.models import Inbox
from app.visits.service import UnknownVisit, apply_billing_reply

logger = logging.getLogger(__name__)

MODULE = "visits"
ATTEMPT_LIMIT = 5  # DL-31
REQUEUE_DELAY_S = 1.0  # D28: short delay before a requeue
LAST_ERROR_MAX = 2000
REPLY_TYPES = {spec.event_type: spec for spec in (BILLING_RECORD_CREATED, BILLING_FAILED)}

Reply = Envelope[BillingRecordCreated] | Envelope[BillingFailed]


def parse_billing_reply(body: bytes) -> Reply:
    try:
        header = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise MalformedMessage("body is not JSON") from error
    spec = REPLY_TYPES.get(header.get("event_type")) if isinstance(header, dict) else None
    if spec is None:
        raise MalformedMessage("not a Billing reply")
    try:
        envelope = Envelope[spec.payload_type].model_validate_json(body)
    except ValidationError as error:
        raise MalformedMessage(str(error).splitlines()[0]) from error
    if envelope.schema_version != spec.schema_version:
        raise MalformedMessage(f"unsupported schema_version {envelope.schema_version}")
    return envelope


class VisitsConsumer:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._backoff: Iterator[float] | None = None  # while the database is unavailable

    async def handle(self, message: RabbitMessage) -> None:
        try:
            envelope = parse_billing_reply(message.body)
        except MalformedMessage as error:
            await message.reject(requeue=False)
            self._log(logging.ERROR, message, "parked", error=error)
            return
        try:
            async with self._sessions.begin() as session:
                outcome = await apply_billing_reply(session, envelope)
        except UnknownVisit as error:
            await message.reject(requeue=False)
            self._log(logging.ERROR, message, "parked", envelope, details=" cause=unknown_visit", error=error)
            return
        except Exception as error:
            await self._failed(message, envelope, error)
            return
        self._backoff = None
        await message.ack()  # after COMMIT
        self._log(logging.INFO, message, outcome.kind, envelope)

    async def _failed(self, message: RabbitMessage, envelope: Reply, error: Exception) -> None:
        if not mechanics.is_database_unavailable(error):
            try:
                attempts = await self._count_failure(envelope, error)
            except Exception as count_error:
                error = count_error  # counting failed too; classify that failure
            else:
                details = f" attempts={attempts} cause=error"
                if attempts >= ATTEMPT_LIMIT:
                    await message.reject(requeue=False)
                    self._log(logging.ERROR, message, "parked", envelope, details=details, error=error)
                else:
                    self._log(logging.ERROR, message, "requeued", envelope, details=details, error=error)
                    await asyncio.sleep(REQUEUE_DELAY_S)
                    await message.nack(requeue=True)
                return
        if mechanics.is_database_unavailable(error):
            self._backoff = self._backoff or backoff_delays(POLL_INTERVAL_S, BACKOFF_CEILING_S)
            delay = next(self._backoff)
            self._log(
                logging.WARNING,
                message,
                "requeued",
                envelope,
                details=f" cause=database_unavailable delay={delay}",
                error=error,
            )
        else:
            delay = REQUEUE_DELAY_S
            self._log(logging.ERROR, message, "requeued", envelope, details=" cause=uncounted", error=error)
        await asyncio.sleep(delay)
        await message.nack(requeue=True)

    async def _count_failure(self, envelope: Reply, error: Exception) -> int:
        """attempts + 1 and last_error, in a short transaction after the ROLLBACK."""
        last_error = f"{type(error).__name__}: {error}"[:LAST_ERROR_MAX]
        statement = insert(Inbox).values(
            event_id=envelope.event_id, event_type=envelope.event_type, attempts=1, last_error=last_error
        )
        statement = statement.on_conflict_do_update(
            index_elements=[Inbox.event_id],
            set_={"attempts": Inbox.attempts + 1, "last_error": statement.excluded.last_error},
        ).returning(Inbox.attempts)
        async with self._sessions.begin() as session:
            return (await session.execute(statement)).scalar_one()

    def _log(
        self,
        level: int,
        message: RabbitMessage,
        outcome: str,
        envelope: Reply | None = None,
        *,
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
    """Subscribe the Visits handler to visits.inbox on `broker` (module-05 section 3)."""
    mechanics.subscribe(broker, INBOX_QUEUES[VISITS_INBOX], VisitsConsumer(sessions).handle)
