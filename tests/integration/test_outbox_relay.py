"""Outbox relay (module-04 tasks 3.1.3 to 3.1.8 and 3.1.10; TDD section 8.1; D6, D19, D25;
contract DL-19, DL-20; NFR1, NFR4)."""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from app.contracts import Envelope, VisitCompleted, format_timestamp
from app.outbox.relay import OutboxRelay, Unroutable
from tests.integration.helpers import (
    Stack,
    collect_messages,
    connected_broker,
    create_visit,
    flush_outbox,
    insert_outbox_rows,
    wait_until,
)

pytestmark = pytest.mark.integration

RELAY_LOGGER = "app.outbox.relay"


async def _rows(conn: asyncpg.Connection, schema: str, ids: list[uuid.UUID]) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"SELECT event_id, published_at, attempts FROM {schema}.outbox"
        " WHERE event_id = ANY($1::uuid[]) ORDER BY occurred_at",
        ids,
    )


async def _delete(conn: asyncpg.Connection, schema: str, ids: list[uuid.UUID]) -> None:
    await conn.execute(f"DELETE FROM {schema}.outbox WHERE event_id = ANY($1::uuid[])", ids)


def _ids(ids: list[uuid.UUID]) -> set[str]:
    return {str(event_id) for event_id in ids}


# 3.1.3 One row, from /complete to billing.inbox


async def test_relay_publishes_a_completion_with_the_tdd_message_properties(
    make_client, visits_db: asyncpg.Connection, visits_engine, events_broker, stack: Stack
) -> None:
    relay = OutboxRelay(schema="visits", engine=visits_engine, broker=events_broker)
    client = make_client()
    visit = await create_visit(client)
    event_id = (await client.post(f"/api/visits/{visit['id']}/complete")).json()[
        "completion_attempt_id"
    ]

    await flush_outbox(relay)

    row = await visits_db.fetchrow("SELECT * FROM visits.outbox WHERE event_id = $1::uuid", event_id)
    assert row["published_at"] is not None
    assert row["attempts"] == 0
    [message] = await collect_messages(stack.rabbitmq_url, "billing.inbox", {event_id})
    assert message.routing_key == "visits.visit_completed"
    assert message.delivery_mode == 2  # persistent
    assert message.message_id == event_id
    assert message.content_type == "application/json"
    body = json.loads(message.body)
    assert body == {
        "event_id": event_id,
        "event_type": "VisitCompleted",
        "schema_version": 1,
        "occurred_at": format_timestamp(row["occurred_at"]),
        "payload": json.loads(row["payload"]),
    }
    Envelope[VisitCompleted].model_validate(body)

    assert (await relay.run_once()).selected == 0
    assert await collect_messages(stack.rabbitmq_url, "billing.inbox", {event_id}, timeout=1.0) == []


# 3.1.4 Batches of 100, in occurred_at order


async def test_relay_publishes_in_batches_of_100_in_order(
    visits_db: asyncpg.Connection, visits_engine, events_broker, stack: Stack
) -> None:
    relay = OutboxRelay(schema="visits", engine=visits_engine, broker=events_broker)
    await flush_outbox(relay)
    ids = await insert_outbox_rows(visits_db, "visits", 150)

    passes = [await relay.run_once() for _ in range(3)]

    assert [(p.selected, p.published) for p in passes] == [(100, 100), (50, 50), (0, 0)]
    delivered = await collect_messages(stack.rabbitmq_url, "billing.inbox", _ids(ids))
    assert [m.message_id for m in delivered] == [str(event_id) for event_id in ids]


# 3.1.5 Two relays at once, SKIP LOCKED


async def test_two_relays_never_publish_a_row_twice(
    visits_db: asyncpg.Connection, visits_engine, events_broker, stack: Stack
) -> None:
    await flush_outbox(OutboxRelay(schema="visits", engine=visits_engine, broker=events_broker))
    ids = await insert_outbox_rows(visits_db, "visits", 40)
    relays = [
        OutboxRelay(schema="visits", engine=visits_engine, broker=events_broker, batch_size=5)
        for _ in range(2)
    ]

    async def drain(relay: OutboxRelay) -> int:
        published = 0
        while (result := await relay.run_once()).selected:
            published += result.published
        return published

    counts = await asyncio.gather(*(drain(relay) for relay in relays))

    assert sum(counts) == 40
    assert all(count > 0 for count in counts), counts  # both relays took rows
    assert all(row["published_at"] for row in await _rows(visits_db, "visits", ids))
    delivered = await collect_messages(stack.rabbitmq_url, "billing.inbox", _ids(ids))
    assert sorted(m.message_id for m in delivered) == sorted(_ids(ids))
    assert await collect_messages(stack.rabbitmq_url, "billing.inbox", _ids(ids), timeout=1.0) == []


# 3.1.6 Broker outage: the event waits, then leaves with no manual step


async def test_relay_recovers_after_a_broker_outage(
    make_client, visits_db: asyncpg.Connection, visits_engine, isolated_rabbitmq
) -> None:
    rabbit = isolated_rabbitmq
    broker = await connected_broker(rabbit.url)
    relay = OutboxRelay(
        schema="visits",
        engine=visits_engine,
        broker=broker,
        poll_interval=0.2,
        backoff_ceiling=2.0,  # the 30 s ceiling is held by the unit test
        publish_timeout=2.0,
    )
    await flush_outbox(relay)
    stop = asyncio.Event()
    task = asyncio.create_task(relay.run_forever(stop))
    try:
        rabbit.stop()
        client = make_client()
        visit = await create_visit(client)
        response = await client.post(f"/api/visits/{visit['id']}/complete")
        assert response.status_code == 202, response.text  # the API never needs the broker
        event_id = uuid.UUID(response.json()["completion_attempt_id"])

        await asyncio.sleep(3.0)
        [row] = await _rows(visits_db, "visits", [event_id])
        assert row["published_at"] is None
        assert row["attempts"] == 0  # DL-20: an outage never counts
        assert not task.done()

        rabbit.start()
        await rabbit.wait_ready()

        async def published() -> bool:
            [current] = await _rows(visits_db, "visits", [event_id])
            return current["published_at"] is not None

        await wait_until(published, timeout=30.0, message="event not published after restart")
        [message] = await collect_messages(rabbit.url, "billing.inbox", {str(event_id)})
        assert message.message_id == str(event_id)
        [row] = await _rows(visits_db, "visits", [event_id])
        assert row["attempts"] == 0
        assert not task.done()
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=10.0)
        await broker.stop()


# 3.1.7 Unroutable: a temporary failure, never counted, never excluded (DL-20)


async def test_unroutable_message_keeps_the_row_selectable(
    visits_db: asyncpg.Connection,
    visits_engine,
    events_broker,
    isolated_rabbitmq,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.outbox.topology import EVENTS_EXCHANGE

    await flush_outbox(OutboxRelay(schema="visits", engine=visits_engine, broker=events_broker))
    broker = await connected_broker(isolated_rabbitmq.url, declare=False)
    await broker.declare_exchange(EVENTS_EXCHANGE)  # no queue bound
    relay = OutboxRelay(schema="visits", engine=visits_engine, broker=broker, publish_timeout=5.0)
    ids = await insert_outbox_rows(visits_db, "visits", 1)
    try:
        with caplog.at_level(logging.ERROR, logger=RELAY_LOGGER):
            for _ in range(2):
                with pytest.raises(Unroutable):
                    await relay.run_once()

        [row] = await _rows(visits_db, "visits", ids)
        assert row["published_at"] is None
        assert row["attempts"] == 0
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert len([line for line in errors if str(ids[0]) in line and "unroutable" in line]) == 2
    finally:
        await broker.stop()
        await _delete(visits_db, "visits", ids)


# 3.1.8 Unknown event type: counted after each pass, excluded at five (DL-19)


@pytest.mark.parametrize(
    ("schema", "unknown_type"),
    [
        pytest.param("visits", "NoSuchEvent", id="visits"),
        pytest.param("billing", "BillingRecordCreated", id="billing"),  # unknown until M05
    ],
)
async def test_unknown_event_type_is_counted_and_then_excluded(
    request: pytest.FixtureRequest,
    events_broker,
    stack: Stack,
    caplog: pytest.LogCaptureFixture,
    schema: str,
    unknown_type: str,
) -> None:
    conn: asyncpg.Connection = request.getfixturevalue(f"{schema}_db")
    engine = request.getfixturevalue(f"{schema}_engine")
    relay = OutboxRelay(schema=schema, engine=engine, broker=events_broker)
    await flush_outbox(relay)
    bad = await insert_outbox_rows(conn, schema, 1, event_type=unknown_type)
    good = await insert_outbox_rows(conn, schema, 2) if schema == "visits" else []
    try:
        with caplog.at_level(logging.ERROR, logger=RELAY_LOGGER):
            first = await relay.run_once()
            assert (first.selected, first.published, first.unknown) == (1 + len(good), len(good), 1)
            assert [row["attempts"] for row in await _rows(conn, schema, bad)] == [1]
            if good:
                assert all(row["published_at"] for row in await _rows(conn, schema, good))
                delivered = await collect_messages(stack.rabbitmq_url, "billing.inbox", _ids(good))
                assert len(delivered) == 2

            for _ in range(4):
                assert (await relay.run_once()).unknown == 1
            assert (await relay.run_once()).selected == 0  # excluded after the fifth pass

        [row] = await _rows(conn, schema, bad)
        assert (row["attempts"], row["published_at"]) == (5, None)
        errors = [r.getMessage() for r in caplog.records if str(bad[0]) in r.getMessage()]
        assert len(errors) == 5
        assert all(unknown_type in line for line in errors)
        assert "excluded" in errors[-1]
    finally:
        await _delete(conn, schema, bad)


# 3.1.10 100 unknown rows do not block good events (DL-19)


async def test_unknown_rows_do_not_block_good_events(
    visits_db: asyncpg.Connection, visits_engine, events_broker, stack: Stack
) -> None:
    relay = OutboxRelay(schema="visits", engine=visits_engine, broker=events_broker)
    await flush_outbox(relay)
    bad = await insert_outbox_rows(
        visits_db, "visits", 100, event_type="NoSuchEvent", start=datetime.now(UTC) - timedelta(hours=1)
    )
    good = await insert_outbox_rows(visits_db, "visits", 3)
    try:
        results = [await relay.run_once() for _ in range(6)]

        assert [(r.selected, r.published, r.unknown) for r in results] == [(100, 0, 100)] * 5 + [
            (3, 3, 0)
        ]
        assert all(row["published_at"] for row in await _rows(visits_db, "visits", good))
        assert len(await collect_messages(stack.rabbitmq_url, "billing.inbox", _ids(good))) == 3
        bad_rows = await _rows(visits_db, "visits", bad)
        assert {(row["attempts"], row["published_at"]) for row in bad_rows} == {(5, None)}

        assert (await relay.run_once()).selected == 0
        assert {row["attempts"] for row in await _rows(visits_db, "visits", bad)} == {5}
    finally:
        await _delete(visits_db, "visits", bad)
