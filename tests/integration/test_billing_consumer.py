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


# Failure paths (module-07 tasks 4.1.5 to 4.1.7 and 4.1.11; TDD section 8.2; D15; DL-35,
# DL-36). They replace M05 test 4.1.9 (overflow requeued every second, interim DL-25 b).


def _bad_times() -> Envelope[VisitCompleted]:
    event_id = uuid.uuid7()
    return new_envelope(
        VISIT_COMPLETED,
        VisitCompleted(
            visit_id=uuid.uuid7(),
            completion_attempt_id=event_id,
            rate=Decimal("25.00"),
            start_date_time=datetime(2026, 11, 11, 11, tzinfo=UTC),
            end_date_time=datetime(2026, 11, 11, 9, tzinfo=UTC),
        ),
        event_id=event_id,
    )


async def _billing_failed(db: asyncpg.Connection, attempt: uuid.UUID) -> list[dict]:
    rows = await db.fetch(
        "SELECT payload FROM billing.outbox WHERE event_type = 'BillingFailed'"
        " AND payload->>'completion_attempt_id' = $1",
        str(attempt),
    )
    return [json.loads(r["payload"]) for r in rows]


async def _inbox_row(db: asyncpg.Connection, event_id: uuid.UUID) -> asyncpg.Record | None:
    return await db.fetchrow("SELECT * FROM billing.inbox WHERE event_id = $1", event_id)


# 4.1.5 Permanent: BillingFailed at once, acknowledged, never parked


async def test_permanent_error_emits_billing_failed_and_acks_once(
    billing_consumer, billing_db: asyncpg.Connection, stack: Stack, caplog: pytest.LogCaptureFixture
) -> None:
    envelope = _bad_times()
    with caplog.at_level(logging.INFO, logger="app.billing"):
        await _publish(stack.rabbitmq_url, envelope)

        async def failed() -> bool:
            return await _inbox_status(billing_db, envelope.event_id) == "failed"

        await wait_until(failed, message="permanent failure not recorded")
        await asyncio.sleep(2.0)
        lines = _consumed(caplog, f"event_id={envelope.event_id}")

    assert len(lines) == 1, [r.getMessage() for r in lines]
    assert lines[0].levelno == logging.ERROR
    assert "outcome=failed" in lines[0].getMessage()
    assert "error_class=permanent" in lines[0].getMessage()
    [reply] = await _billing_failed(billing_db, envelope.event_id)
    assert reply["error_class"] == "permanent"
    assert await billing_db.fetchval(
        "SELECT count(*) FROM billing.billing_record WHERE visit_id = $1", envelope.payload.visit_id
    ) == 0
    assert await collect_messages(stack.rabbitmq_url, "billing.parking", {str(envelope.event_id)}, timeout=1.0) == []


# 4.1.6 Stable transient: counted 5 times, BillingFailed transient_exhausted, parked


async def test_stable_transient_error_is_exhausted_after_five_attempts(
    billing_consumer, billing_db: asyncpg.Connection, stack: Stack, caplog: pytest.LogCaptureFixture
) -> None:
    from tests.integration.helpers import failing_insert_trigger

    envelope = _visit_completed()
    async with failing_insert_trigger(stack, envelope.payload.visit_id):
        with caplog.at_level(logging.INFO, logger="app.billing"):
            await _publish(stack.rabbitmq_url, envelope)
            [parked] = await collect_messages(
                stack.rabbitmq_url, "billing.parking", {str(envelope.event_id)}, timeout=20.0
            )
            lines = _consumed(caplog, f"event_id={envelope.event_id}")

    outcomes = [r.getMessage().split("outcome=")[1].split()[0] for r in lines]
    assert outcomes == ["requeued"] * 4 + ["parked"], outcomes
    assert "attempts=5" in lines[-1].getMessage()
    assert "error_class=transient_exhausted" in lines[-1].getMessage()
    assert lines[-1].levelno == logging.ERROR
    [death] = parked.headers["x-death"]
    assert (death["queue"], death["reason"]) == ("billing.inbox", "rejected")
    inbox = await _inbox_row(billing_db, envelope.event_id)
    assert (inbox["status"], inbox["attempts"]) == ("failed", 5)
    assert "injected failure" in inbox["last_error"]
    [reply] = await _billing_failed(billing_db, envelope.event_id)
    assert reply["error_class"] == "transient_exhausted"
    assert await billing_db.fetchval(
        "SELECT count(*) FROM billing.billing_record WHERE visit_id = $1", envelope.payload.visit_id
    ) == 0

    good = _visit_completed()
    await _publish(stack.rabbitmq_url, good)

    async def good_processed() -> bool:
        return await _inbox_status(billing_db, good.event_id) == "processed"

    await wait_until(good_processed, message="message after the exhausted one not processed")


# 4.1.7 Database unavailable: backoff, never parked, never counted (DL-35; dedicated broker)


async def test_database_outage_requeues_with_backoff_and_never_counts(
    isolated_rabbitmq, billing_db: asyncpg.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    import socket

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
    unreachable = create_async_engine(f"postgresql+asyncpg://billing_app:billing_app@127.0.0.1:{closed_port}/jiris")
    envelope = _visit_completed()
    broker = await start_billing_consumer(
        isolated_rabbitmq.url, async_sessionmaker(unreachable, expire_on_commit=False)
    )
    try:
        with caplog.at_level(logging.INFO, logger="app.billing"):
            await _publish(isolated_rabbitmq.url, envelope)

            async def three_deliveries() -> bool:
                return len(_consumed(caplog, f"event_id={envelope.event_id}")) >= 3

            await wait_until(three_deliveries, timeout=15.0, message="message not redelivered")
            first, second, third = _consumed(caplog, f"event_id={envelope.event_id}")[:3]
    finally:
        await broker.stop()
        await unreachable.dispose()

    for record in (first, second, third):
        assert "outcome=requeued" in record.getMessage()
        assert "cause=database_unavailable" in record.getMessage()
    gap_one, gap_two = second.created - first.created, third.created - second.created
    assert gap_one >= 0.5 and gap_two >= 1.0 and gap_two > gap_one, (gap_one, gap_two)
    assert await collect_messages(isolated_rabbitmq.url, "billing.parking", {str(envelope.event_id)}, timeout=1.0) == []
    [kept] = await collect_messages(isolated_rabbitmq.url, "billing.inbox", {str(envelope.event_id)})
    assert kept.message_id == str(envelope.event_id)
    assert await _inbox_row(billing_db, envelope.event_id) is None


# 4.1.11 Concurrent duplicate delivery: one record, no BillingFailed (DL-36: 23505 transient)


async def test_concurrent_duplicate_delivery_gives_one_record_and_no_billing_failed(
    billing_consumer, billing_sessions, billing_db: asyncpg.Connection, stack: Stack
) -> None:
    second_consumer = await start_billing_consumer(stack.rabbitmq_url, billing_sessions)
    try:
        envelope = _visit_completed()
        await asyncio.gather(_publish(stack.rabbitmq_url, envelope), _publish(stack.rabbitmq_url, envelope))

        async def processed() -> bool:
            return await _inbox_status(billing_db, envelope.event_id) == "processed"

        await wait_until(processed, message="VisitCompleted not processed")
        await asyncio.sleep(2.0)  # both deliveries settled by now
    finally:
        await second_consumer.stop()

    assert await billing_db.fetchval(
        "SELECT count(*) FROM billing.billing_record WHERE visit_id = $1", envelope.payload.visit_id
    ) == 1
    assert await billing_db.fetchval(
        "SELECT count(*) FROM billing.outbox WHERE event_type = 'BillingRecordCreated'"
        " AND payload->>'visit_id' = $1",
        str(envelope.payload.visit_id),
    ) == 1
    assert await _billing_failed(billing_db, envelope.event_id) == []
