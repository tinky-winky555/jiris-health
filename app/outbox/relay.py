"""Polling outbox relay, parametrised by schema and role (TDD section 8.1; D19, D25;
contract DL-19, DL-20).

One pass is one transaction: select unpublished rows with FOR UPDATE SKIP LOCKED,
publish each with a publisher confirm, mark it published, COMMIT. A crash after a
confirm and before COMMIT publishes the row again; consumers de-duplicate by
event_id. Error classes:

- broker unavailable, connection lost, negative confirm or publish timeout:
  ROLLBACK, back off, retry forever; `attempts` unchanged, so an outage of any
  length never excludes an event (D6);
- message returned as unroutable: the same, plus an ERROR line;
- event type without a routing key: the row is skipped, and after the pass a short
  transaction adds 1 to `attempts`; at 5 the row leaves the selection.

Imports neither module; the schema name is checked before it enters SQL.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from aiormq.exceptions import PublishError
from faststream.rabbit import RabbitBroker
from pamqp.commands import Basic
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.asyncio import AsyncEngine

from app.contracts import format_timestamp, routing_key_for
from app.outbox.topology import EVENTS_EXCHANGE

logger = logging.getLogger(__name__)

SCHEMAS = frozenset({"visits", "billing"})
UNKNOWN_TYPE_ATTEMPT_LIMIT = 5  # DL-19
BATCH_SIZE = 100  # D25
POLL_INTERVAL_S = 0.5  # D25
BACKOFF_CEILING_S = 30.0  # D25
PUBLISH_TIMEOUT_S = 10.0


def backoff_delays(initial: float, ceiling: float) -> Iterator[float]:
    """initial, doubled each time, never above ceiling (TDD section 8.1)."""
    delay = initial
    while True:
        yield min(delay, ceiling)
        delay = min(delay * 2, ceiling)


def message_body(row: Mapping[str, Any]) -> bytes:
    """The envelope of TDD section 7, rebuilt from the outbox columns."""
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    envelope = {
        "event_id": str(row["event_id"]),
        "event_type": row["event_type"],
        "schema_version": row["schema_version"],
        "occurred_at": format_timestamp(row["occurred_at"]),
        "payload": payload,
    }
    return json.dumps(envelope, separators=(",", ":")).encode()


class PublishFailed(Exception):
    def __init__(self, event_id: uuid.UUID, cause: BaseException) -> None:
        super().__init__(f"event_id={event_id} cause={cause!r}")
        self.event_id = event_id
        self.cause = cause


class BrokerUnavailable(PublishFailed):
    """No confirm: connection lost, broker down, negative confirm or timeout."""


class Unroutable(PublishFailed):
    """The broker returned the mandatory message: no queue is bound for its key."""


@dataclass(frozen=True)
class PassResult:
    selected: int
    published: int
    unknown: int


class OutboxRelay:
    def __init__(
        self,
        *,
        schema: str,
        engine: AsyncEngine,
        broker: RabbitBroker,
        batch_size: int = BATCH_SIZE,
        poll_interval: float = POLL_INTERVAL_S,
        backoff_ceiling: float = BACKOFF_CEILING_S,
        publish_timeout: float = PUBLISH_TIMEOUT_S,
    ) -> None:
        if schema not in SCHEMAS:
            raise ValueError(f"unknown outbox schema: {schema!r}")
        self._schema = schema
        self._engine = engine
        self._broker = broker
        self._batch_size = batch_size
        self._poll_interval = poll_interval
        self._backoff_ceiling = backoff_ceiling
        self._publish_timeout = publish_timeout
        self._select = text(
            "SELECT event_id, event_type, schema_version, payload, occurred_at"
            f" FROM {schema}.outbox"
            " WHERE published_at IS NULL AND attempts < :attempt_limit"
            " ORDER BY occurred_at LIMIT :batch_size FOR UPDATE SKIP LOCKED"
        )
        self._mark_published = text(
            f"UPDATE {schema}.outbox SET published_at = now() WHERE event_id = :event_id"
        )
        self._count_unknown = text(
            f"UPDATE {schema}.outbox SET attempts = attempts + 1 WHERE event_id = ANY(:event_ids)"
            " RETURNING event_id, event_type, attempts"
        ).bindparams(bindparam("event_ids", type_=ARRAY(UUID(as_uuid=True))))

    async def run_once(self) -> PassResult:
        """One pass; raises PublishFailed after ROLLBACK when the broker fails."""
        unknown: list[uuid.UUID] = []
        published: list[Mapping[str, Any]] = []
        try:
            async with self._engine.begin() as conn:
                rows = (
                    await conn.execute(
                        self._select,
                        {
                            "attempt_limit": UNKNOWN_TYPE_ATTEMPT_LIMIT,
                            "batch_size": self._batch_size,
                        },
                    )
                ).mappings().all()
                for row in rows:
                    routing_key = routing_key_for(row["event_type"])
                    if routing_key is None:
                        unknown.append(row["event_id"])
                        continue
                    await self._publish(row, routing_key)
                    await conn.execute(self._mark_published, {"event_id": row["event_id"]})
                    published.append(row)
        finally:
            if unknown:
                await self._record_unknown(unknown)
        for row in published:
            logger.info(
                "event published schema=%s event_id=%s event_type=%s outcome=published",
                self._schema,
                row["event_id"],
                row["event_type"],
            )
        return PassResult(selected=len(rows), published=len(published), unknown=len(unknown))

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Pass after pass until `stop` is set; a running pass always finishes first."""
        logger.info("relay started schema=%s", self._schema)
        delays: Iterator[float] | None = None
        while not stop.is_set():
            try:
                result = await self.run_once()
            except Exception as error:  # broker or database failure: back off, never give up
                if not isinstance(error, PublishFailed):
                    logger.warning("relay pass failed schema=%s error=%r", self._schema, error)
                delays = delays or backoff_delays(self._poll_interval, self._backoff_ceiling)
                await _sleep(stop, next(delays))
                continue
            delays = None
            if result.selected == 0:
                await _sleep(stop, self._poll_interval)
        logger.info("relay stopped schema=%s", self._schema)

    async def _publish(self, row: Mapping[str, Any], routing_key: str) -> None:
        event_id = row["event_id"]
        try:
            confirm = await asyncio.wait_for(
                self._broker.publish(
                    message_body(row),
                    exchange=EVENTS_EXCHANGE,
                    routing_key=routing_key,
                    mandatory=True,
                    persist=True,
                    message_id=str(event_id),
                    content_type="application/json",
                    timeout=self._publish_timeout,
                ),
                self._publish_timeout + 1.0,
            )
        except PublishError as error:
            logger.error(
                "event unroutable schema=%s event_id=%s event_type=%s routing_key=%s"
                " outcome=rolled_back",
                self._schema,
                event_id,
                row["event_type"],
                routing_key,
            )
            raise Unroutable(event_id, error) from error
        except Exception as error:
            logger.warning(
                "broker unavailable schema=%s event_id=%s error=%r outcome=rolled_back",
                self._schema,
                event_id,
                error,
            )
            raise BrokerUnavailable(event_id, error) from error
        if not isinstance(confirm, Basic.Ack):
            logger.warning(
                "publish not confirmed schema=%s event_id=%s confirm=%r outcome=rolled_back",
                self._schema,
                event_id,
                confirm,
            )
            raise BrokerUnavailable(event_id, RuntimeError(f"no ack: {confirm!r}"))

    async def _record_unknown(self, event_ids: list[uuid.UUID]) -> None:
        async with self._engine.begin() as conn:
            counted = (await conn.execute(self._count_unknown, {"event_ids": event_ids})).all()
        for event_id, event_type, attempts in counted:
            logger.error(
                "unknown event type schema=%s event_id=%s event_type=%s attempts=%d outcome=%s",
                self._schema,
                event_id,
                event_type,
                attempts,
                "excluded" if attempts >= UNKNOWN_TYPE_ATTEMPT_LIMIT else "skipped",
            )


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), seconds)
    except TimeoutError:
        pass
