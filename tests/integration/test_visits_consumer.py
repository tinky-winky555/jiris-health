"""Visits consumer through RabbitMQ (module-06 tasks 4.1.9 to 4.1.11 and 4.1.16; TDD section 6.4;
R9; contract DL-30, DL-31)."""

import asyncio
import json
import logging
import socket
import uuid

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.integration.helpers import (
    Stack,
    billing_reply,
    collect_messages,
    pending_visit,
    publish_raw,
    start_visits_consumer,
    wait_until,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("no_foreign_consumers", "clean_queues"),  # DL-32, DL-27
]

CONSUMER_LOGGER = "app.visits.consumer"


def _routing_key(envelope) -> str:
    return "billing.failed" if envelope.event_type == "BillingFailed" else "billing.record_created"


async def _publish(rabbitmq_url: str, envelope) -> str:
    return await publish_raw(
        rabbitmq_url,
        envelope.model_dump_json().encode(),
        routing_key=_routing_key(envelope),
        message_id=str(envelope.event_id),
    )


def _consumed(caplog: pytest.LogCaptureFixture, needle: str) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == CONSUMER_LOGGER
        and r.getMessage().startswith("event consumed module=visits")
        and needle in r.getMessage()
    ]


async def _status(client, visit_id: str) -> str:
    return (await client.get(f"/api/visits/{visit_id}")).json()["status"]


# 4.1.9 Applied and acknowledged once


async def test_consumer_completes_a_visit_and_acks_the_reply_once(
    visits_consumer, make_client, stack: Stack, caplog: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    visit_id, attempt = await pending_visit(client)
    reply = billing_reply(visit_id, attempt)
    with caplog.at_level(logging.INFO, logger="app.visits"):
        await _publish(stack.rabbitmq_url, reply)

        async def completed() -> bool:
            return await _status(client, visit_id) == "Completed"

        await wait_until(completed, message="reply not applied")
        await asyncio.sleep(2.0)  # a redelivery, if any, would be logged by now
        lines = [r.getMessage() for r in _consumed(caplog, f"event_id={reply.event_id}")]

    assert len(lines) == 1, lines
    assert f"visit_id={visit_id}" in lines[0]
    assert "event_type=BillingRecordCreated" in lines[0]
    assert "outcome=completed" in lines[0]
    assert "redelivered=False" in lines[0]


# 4.1.10 Malformed and unknown visit: parked once (R9, DL-30, DL-31)


def _malformed_bodies() -> list:
    good = json.loads(billing_reply(str(uuid.uuid7()), str(uuid.uuid7())).model_dump_json())
    payload_n = {**good, "payload": {"n": 1}}
    visit_completed = {**good, "event_type": "VisitCompleted"}
    return [
        pytest.param(b"not json", id="not-json"),
        pytest.param(json.dumps(payload_n).encode(), id="payload-n-1"),
        pytest.param(json.dumps(visit_completed).encode(), id="visit-completed"),
        pytest.param(json.dumps({**good, "schema_version": 2}).encode(), id="other-version"),
        pytest.param(json.dumps(good).encode(), id="unknown-visit"),
    ]


@pytest.mark.parametrize("body", _malformed_bodies())
async def test_malformed_reply_or_unknown_visit_is_parked_once(
    visits_consumer,
    make_client,
    visits_db: asyncpg.Connection,
    stack: Stack,
    caplog: pytest.LogCaptureFixture,
    body: bytes,
) -> None:
    client = make_client()
    with caplog.at_level(logging.INFO, logger="app.visits"):
        bad_id = await publish_raw(stack.rabbitmq_url, body, routing_key="billing.record_created")
        visit_id, attempt = await pending_visit(client)
        await _publish(stack.rabbitmq_url, billing_reply(visit_id, attempt))

        [parked] = await collect_messages(stack.rabbitmq_url, "visits.parking", {bad_id})
        [death] = parked.headers["x-death"]
        assert (death["queue"], death["reason"], death["count"]) == ("visits.inbox", "rejected", 1)
        assert parked.body == body

        async def next_completed() -> bool:
            return await _status(client, visit_id) == "Completed"

        await wait_until(next_completed, message="reply after the parked one not applied")
        lines = _consumed(caplog, f"message_id={bad_id}")

    assert len(lines) == 1, [r.getMessage() for r in lines]
    assert lines[0].levelno == logging.ERROR
    assert "outcome=parked" in lines[0].getMessage()
    if body.startswith(b"{") and b'"event_id"' in body:
        event_id = uuid.UUID(json.loads(body)["event_id"])
        assert await visits_db.fetchval("SELECT count(*) FROM visits.inbox WHERE event_id = $1", event_id) == 0
    assert await collect_messages(stack.rabbitmq_url, "visits.inbox", {bad_id}, timeout=1.0) == []


# 4.1.11 Database unavailable: requeued with backoff, never parked, never counted (DL-31)


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_database_outage_requeues_with_backoff_and_never_parks(
    isolated_rabbitmq, make_client, visits_db: asyncpg.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    visit_id, attempt = await pending_visit(make_client())
    reply = billing_reply(visit_id, attempt)
    unreachable = create_async_engine(
        f"postgresql+asyncpg://visits_app:visits_app@127.0.0.1:{_closed_port()}/jiris"
    )
    broker = await start_visits_consumer(
        isolated_rabbitmq.url, async_sessionmaker(unreachable, expire_on_commit=False)
    )
    try:
        with caplog.at_level(logging.INFO, logger="app.visits"):
            await _publish(isolated_rabbitmq.url, reply)

            async def three_deliveries() -> bool:
                return len(_consumed(caplog, f"event_id={reply.event_id}")) >= 3

            await wait_until(three_deliveries, timeout=15.0, message="reply not redelivered")
            first, second, third = _consumed(caplog, f"event_id={reply.event_id}")[:3]
    finally:
        await broker.stop()
        await unreachable.dispose()

    for record in (first, second, third):
        assert "outcome=requeued" in record.getMessage()
        assert "cause=database_unavailable" in record.getMessage()
    gap_one, gap_two = second.created - first.created, third.created - second.created
    assert gap_one >= 0.5 and gap_two >= 1.0 and gap_two > gap_one, (gap_one, gap_two)
    assert await collect_messages(isolated_rabbitmq.url, "visits.parking", {str(reply.event_id)}, timeout=1.0) == []
    [kept] = await collect_messages(isolated_rabbitmq.url, "visits.inbox", {str(reply.event_id)})
    assert kept.message_id == str(reply.event_id)
    assert await visits_db.fetchval("SELECT count(*) FROM visits.inbox WHERE event_id = $1", reply.event_id) == 0


# 4.1.16 Stable failure: counted 5 times, then parked; the next reply is processed (DL-31)


async def test_stable_failure_is_parked_after_five_counted_attempts(
    visits_consumer,
    make_client,
    visits_db: asyncpg.Connection,
    stack: Stack,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = make_client()
    failing_visit, failing_attempt = await pending_visit(client)
    name = f"m06_fail_{uuid.uuid4().hex[:12]}"
    migrator = await asyncpg.connect(
        stack.env["MIGRATIONS_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    await migrator.execute(
        f"CREATE FUNCTION visits.{name}() RETURNS trigger LANGUAGE plpgsql AS"
        " $$ BEGIN RAISE EXCEPTION 'injected failure for the M06 test'; END $$"
    )
    await migrator.execute(
        f"CREATE TRIGGER {name} BEFORE UPDATE ON visits.visit FOR EACH ROW"
        f" WHEN (OLD.id = '{failing_visit}'::uuid) EXECUTE FUNCTION visits.{name}()"
    )
    try:
        failing = billing_reply(failing_visit, failing_attempt)
        with caplog.at_level(logging.INFO, logger="app.visits"):
            await _publish(stack.rabbitmq_url, failing)
            [parked] = await collect_messages(
                stack.rabbitmq_url, "visits.parking", {str(failing.event_id)}, timeout=20.0
            )
            lines = _consumed(caplog, f"event_id={failing.event_id}")

        assert [r.getMessage().split("outcome=")[1].split()[0] for r in lines] == ["requeued"] * 4 + ["parked"]
        assert all("attempts=" in r.getMessage() for r in lines)
        assert lines[-1].levelno == logging.ERROR
        assert "attempts=5" in lines[-1].getMessage()
        [death] = parked.headers["x-death"]
        assert (death["queue"], death["reason"]) == ("visits.inbox", "rejected")
        inbox = await visits_db.fetchrow("SELECT * FROM visits.inbox WHERE event_id = $1", failing.event_id)
        assert (inbox["attempts"], inbox["processed_at"]) == (5, None)
        assert "injected failure for the M06 test" in inbox["last_error"]

        visit_id, attempt = await pending_visit(client)
        await _publish(stack.rabbitmq_url, billing_reply(visit_id, attempt))

        async def next_completed() -> bool:
            return await _status(client, visit_id) == "Completed"

        await wait_until(next_completed, message="reply after the parked one not applied")
        assert await _status(client, failing_visit) == "Scheduled"
    finally:
        await migrator.execute(f"DROP TRIGGER IF EXISTS {name} ON visits.visit")
        await migrator.execute(f"DROP FUNCTION IF EXISTS visits.{name}()")
        await migrator.close()
