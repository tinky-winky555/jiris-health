"""Billing consumer through RabbitMQ (module-05 tasks 4.1.7 to 4.1.9; TDD section 8.2; R9, D6;
contract DL-25)."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg
import pytest

from app.contracts import (
    BILLING_RECORD_CREATED,
    VISIT_COMPLETED,
    BillingRecordCreated,
    Envelope,
    VisitCompleted,
    new_envelope,
)
from app.outbox.relay import OutboxRelay
from tests.integration.helpers import (
    Stack,
    collect_messages,
    flush_outbox,
    publish_raw,
    start_billing_consumer,
    wait_until,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("no_foreign_consumers", "clean_queues"),  # DL-32, DL-27
]

CONSUMER_LOGGER = "app.billing.consumer"
ROUTING_KEY = VISIT_COMPLETED.routing_key


def _visit_completed(rate: str = "25.00") -> Envelope[VisitCompleted]:
    event_id = uuid.uuid7()
    return new_envelope(
        VISIT_COMPLETED,
        VisitCompleted(
            visit_id=uuid.uuid7(),
            completion_attempt_id=event_id,
            rate=Decimal(rate),
            start_date_time=datetime(2026, 11, 11, 9, tzinfo=UTC),
            end_date_time=datetime(2026, 11, 11, 11, tzinfo=UTC),
        ),
        event_id=event_id,
    )


async def _publish(rabbitmq_url: str, envelope: Envelope) -> str:
    return await publish_raw(
        rabbitmq_url,
        envelope.model_dump_json().encode(),
        routing_key=ROUTING_KEY,
        message_id=str(envelope.event_id),
    )


def _consumed(caplog: pytest.LogCaptureFixture, needle: str) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == CONSUMER_LOGGER and r.getMessage().startswith("event consumed") and needle in r.getMessage()
    ]


async def _inbox_status(db: asyncpg.Connection, event_id: uuid.UUID) -> str | None:
    return await db.fetchval("SELECT status FROM billing.inbox WHERE event_id = $1", event_id)


# 4.1.7 Through the broker: processed, acknowledged once, reply routed to visits.inbox


async def test_consumer_bills_a_visit_completed_and_acks_it_once(
    billing_consumer,
    billing_db: asyncpg.Connection,
    billing_engine,
    events_broker,
    stack: Stack,
    caplog: pytest.LogCaptureFixture,
) -> None:
    envelope = _visit_completed()
    with caplog.at_level(logging.INFO, logger="app.billing"):
        await _publish(stack.rabbitmq_url, envelope)

        async def processed() -> bool:
            return await _inbox_status(billing_db, envelope.event_id) == "processed"

        await wait_until(processed, message="VisitCompleted not processed")
        [record] = await billing_db.fetch(
            "SELECT * FROM billing.billing_record WHERE visit_id = $1", envelope.payload.visit_id
        )
        assert record["amount"] == Decimal("50.00")

        await asyncio.sleep(2.0)  # a redelivery, if any, would be logged by now
        lines = [r.getMessage() for r in _consumed(caplog, f"event_id={envelope.event_id}")]
        assert len(lines) == 1, lines
        assert "outcome=processed" in lines[0]
        assert "redelivered=False" in lines[0]
        assert f"visit_id={envelope.payload.visit_id}" in lines[0]

    await flush_outbox(OutboxRelay(schema="billing", engine=billing_engine, broker=events_broker))
    reply_id = await billing_db.fetchval(
        "SELECT event_id::text FROM billing.outbox WHERE payload->>'completion_attempt_id' = $1",
        str(envelope.event_id),
    )
    [reply] = await collect_messages(stack.rabbitmq_url, "visits.inbox", {reply_id})
    assert reply.routing_key == BILLING_RECORD_CREATED.routing_key
    assert reply.message_id == reply_id
    body = Envelope[BillingRecordCreated].model_validate_json(reply.body)
    assert body.payload.billing_record_id == record["id"]
    assert body.payload.completion_attempt_id == envelope.event_id


# 4.1.8 Malformed messages are parked once and never loop (R9, DL-25)


def _bad_envelope(**overrides: object) -> bytes:
    raw = json.loads(_visit_completed().model_dump_json())
    raw.update(overrides)
    return json.dumps(raw).encode()


MALFORMED = [
    pytest.param(lambda: b"not json", id="not-json"),
    pytest.param(lambda: b'{"x": 1}', id="no-envelope-fields"),
    pytest.param(lambda: _bad_envelope(payload={"n": 1}), id="payload-n-1"),
    pytest.param(lambda: _bad_envelope(event_type="VisitStarted"), id="other-type"),
    pytest.param(lambda: _bad_envelope(schema_version=2), id="other-version"),
]


@pytest.mark.parametrize("make_body", MALFORMED)
async def test_malformed_message_is_parked_once_and_the_next_is_processed(
    billing_consumer,
    billing_db: asyncpg.Connection,
    stack: Stack,
    caplog: pytest.LogCaptureFixture,
    make_body,
) -> None:
    body = make_body()
    with caplog.at_level(logging.INFO, logger="app.billing"):
        bad_id = await publish_raw(stack.rabbitmq_url, body, routing_key=ROUTING_KEY)
        good = _visit_completed()
        await _publish(stack.rabbitmq_url, good)

        [parked] = await collect_messages(stack.rabbitmq_url, "billing.parking", {bad_id})

        [death] = parked.headers["x-death"]
        assert (death["queue"], death["reason"], death["count"]) == ("billing.inbox", "rejected", 1)
        assert parked.body == body

        async def good_processed() -> bool:
            return await _inbox_status(billing_db, good.event_id) == "processed"

        await wait_until(good_processed, message="message after the malformed one not processed")
        lines = [r.getMessage() for r in _consumed(caplog, f"message_id={bad_id}")]
        assert len(lines) == 1, lines
        assert "outcome=parked" in lines[0]

    if body.startswith(b"{") and b"event_id" in body:
        event_id = uuid.UUID(json.loads(body)["event_id"])
        assert await _inbox_status(billing_db, event_id) is None
    assert await collect_messages(stack.rabbitmq_url, "billing.inbox", {bad_id}, timeout=1.0) == []


# 4.1.9 Interim failure: ROLLBACK, ERROR, requeue after 1 s (DL-25; dedicated broker)


async def test_failed_transaction_requeues_the_message_after_one_second(
    billing_sessions,
    billing_db: asyncpg.Connection,
    isolated_rabbitmq,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 9999999999.99 per hour for 2 hours overflows numeric(12,2): the INSERT fails.
    envelope = _visit_completed(rate="9999999999.99")
    broker = await start_billing_consumer(isolated_rabbitmq.url, billing_sessions)
    try:
        with caplog.at_level(logging.INFO, logger="app.billing"):
            await _publish(isolated_rabbitmq.url, envelope)

            async def requeued_twice() -> bool:
                return len(_consumed(caplog, f"event_id={envelope.event_id}")) >= 2

            await wait_until(requeued_twice, message="message not delivered again")
            first, second = _consumed(caplog, f"event_id={envelope.event_id}")[:2]
    finally:
        await broker.stop()

    for record in (first, second):
        assert record.levelno == logging.ERROR
        assert "outcome=requeued" in record.getMessage()
    assert "redelivered=False" in first.getMessage()
    assert "redelivered=True" in second.getMessage()
    assert second.created - first.created >= 1.0
    assert await _inbox_status(billing_db, envelope.event_id) is None
    assert await billing_db.fetchval(
        "SELECT count(*) FROM billing.billing_record WHERE visit_id = $1", envelope.payload.visit_id
    ) == 0
    assert await billing_db.fetchval(
        "SELECT count(*) FROM billing.outbox WHERE payload->>'visit_id' = $1",
        str(envelope.payload.visit_id),
    ) == 0
