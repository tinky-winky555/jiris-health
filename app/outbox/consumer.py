"""Consumer mechanics shared by the Billing and Visits consumers (TDD sections 6.4 and 8.2;
contract DL-25, DL-31, DL-33).

- Subscription on a queue object of app/outbox/topology.py, with `AckPolicy.MANUAL`: FastStream
  never settles a message; the module consumer does, after COMMIT. The library default,
  reject on error, would park an event on any exception (D6).
- A raw body decoder: FastStream's JSON decoder would fail on a malformed body before the
  handler runs, and under manual acknowledgement that message would stay unsettled for ever.
- `is_database_unavailable()`: the failure class that is retried with backoff and never
  counted, as in the relay.
- One log line per consumed message.

Imports neither module.
"""

import logging
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import asyncpg
from faststream import AckPolicy
from faststream.message import StreamMessage
from faststream.rabbit import RabbitBroker, RabbitQueue
from faststream.rabbit.annotations import RabbitMessage
from faststream.rabbit.schemas import Channel
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

PREFETCH = 10

Handler = Callable[[RabbitMessage], Awaitable[None]]

_UNAVAILABLE = (
    OSError,  # includes ConnectionError: refused, reset, host unreachable
    TimeoutError,
    asyncpg.InterfaceError,  # includes ConnectionDoesNotExistError
    asyncpg.PostgresConnectionError,
    asyncpg.CannotConnectNowError,
    asyncpg.TooManyConnectionsError,
    OperationalError,
    InterfaceError,
)


class MalformedMessage(Exception):
    """The body is not an envelope this consumer accepts (R9): parked, never retried."""


def error_chain(error: BaseException) -> Iterator[BaseException]:
    """The error, its `orig` (SQLAlchemy), causes and contexts, each once."""
    seen: set[int] = set()
    pending: list[BaseException | None] = [error]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending.extend([getattr(current, "orig", None), current.__cause__, current.__context__])


def is_database_unavailable(error: BaseException) -> bool:
    """True when the database cannot be reached or the connection was lost (DL-31)."""
    for current in error_chain(error):
        if isinstance(current, DBAPIError) and current.connection_invalidated:
            return True
        if isinstance(current, _UNAVAILABLE):
            return True
    return False


async def raw_body(message: StreamMessage[Any]) -> bytes:
    return message.body


def subscribe(broker: RabbitBroker, queue: RabbitQueue, handler: Handler) -> None:
    """Subscribe `handler` to `queue`; the handler settles every message itself."""

    @broker.subscriber(
        queue,
        ack_policy=AckPolicy.MANUAL,
        channel=Channel(prefetch_count=PREFETCH),
        decoder=raw_body,
        title=queue.name,
    )
    async def on_message(message: RabbitMessage) -> None:
        await handler(message)


def log_consumed(
    logger: logging.Logger,
    level: int,
    module: str,
    message: RabbitMessage,
    outcome: str,
    *,
    event_id: object = "-",
    event_type: object = "-",
    visit_id: object = "-",
    details: str = "",
    error: BaseException | None = None,
) -> None:
    """One line per consumed message (contract section 3, Logging); no payload bodies."""
    logger.log(
        level,
        "event consumed module=%s event_id=%s event_type=%s visit_id=%s message_id=%s"
        " redelivered=%s outcome=%s%s%s",
        module,
        event_id,
        event_type,
        visit_id,
        message.message_id or "-",
        message.raw_message.redelivered,
        outcome,
        details,
        f" error={error!r}" if error else "",
    )
