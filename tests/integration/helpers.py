"""Shared steps for integration tests."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

EVENTUAL_TIMEOUT_S = 10.0  # D28
POLL_INTERVAL_S = 0.1


class WorkerNotReady(Exception):
    """The worker process did not put a consumer on both inbox queues in time.

    T1 expects exactly this error until M06 (contract DL-17); any other error
    in the worker fixture fails the test.
    """


@dataclass(frozen=True)
class Stack:
    """Connection settings of the stack started by the integration fixtures."""

    env: dict[str, str]
    visits_dsn: str
    billing_dsn: str
    rabbitmq_url: str


async def create_visit(
    client: httpx.AsyncClient,
    *,
    start: str = "2026-11-11T09:00:00Z",
    end: str = "2026-11-11T11:00:00Z",
    rate: str = "25.00",
    description: str = "Morning care visit",
) -> dict:
    response = await client.post(
        "/api/visits",
        json={
            "start_date_time": start,
            "end_date_time": end,
            "description": description,
            "rate": rate,
        },
    )
    assert response.status_code == 201, response.text
    visit = response.json()
    assert visit["status"] == "Scheduled"
    return visit


async def start_visit(client: httpx.AsyncClient, visit_id: str) -> dict:
    response = await client.post(f"/api/visits/{visit_id}/start")
    assert response.status_code == 200, response.text
    visit = response.json()
    assert visit["status"] == "In Progress"
    return visit


async def wait_for_visit_status(
    client: httpx.AsyncClient, visit_id: str, status: str, timeout: float = EVENTUAL_TIMEOUT_S
) -> dict:
    """Poll GET /api/visits/{id} until the visit reaches the status (TDD section 11)."""
    deadline = time.monotonic() + timeout
    visit: dict = {}
    while time.monotonic() < deadline:
        response = await client.get(f"/api/visits/{visit_id}")
        assert response.status_code == 200, response.text
        visit = response.json()
        if visit["status"] == status:
            return visit
        await asyncio.sleep(POLL_INTERVAL_S)
    raise AssertionError(f"visit {visit_id} did not reach {status!r} in {timeout} s: {visit}")


# Broker and outbox helpers (M04)


@dataclass(frozen=True)
class Delivered:
    """What a test needs to know about one message taken from a queue."""

    message_id: str | None
    routing_key: str | None
    body: bytes
    content_type: str | None
    delivery_mode: int | None
    headers: dict


async def collect_messages(
    rabbitmq_url: str,
    queue: str,
    message_ids: set[str],
    *,
    timeout: float = EVENTUAL_TIMEOUT_S,
    reject: bool = False,
) -> list[Delivered]:
    """Take messages from `queue` until every id in `message_ids` is seen or the timeout ends.

    Messages of other tests are acknowledged and dropped: no consumer exists before M05,
    and every assertion filters by message id. Wanted messages are acknowledged, or
    rejected without requeue when `reject` is set. Returns them in arrival order.
    """
    import aio_pika

    wanted: list[Delivered] = []
    deadline = time.monotonic() + timeout
    connection = await aio_pika.connect(rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        source = await channel.declare_queue(queue, passive=True)
        while time.monotonic() < deadline and len(wanted) < len(message_ids):
            message = await source.get(no_ack=False, fail=False)
            if message is None:
                await asyncio.sleep(POLL_INTERVAL_S / 2)
                continue
            if message.message_id in message_ids:
                wanted.append(
                    Delivered(
                        message_id=message.message_id,
                        routing_key=message.routing_key,
                        body=message.body,
                        content_type=message.content_type,
                        delivery_mode=int(message.delivery_mode) if message.delivery_mode else None,
                        headers=dict(message.headers or {}),
                    )
                )
                if reject:
                    await message.reject(requeue=False)
                    continue
            await message.ack()
    return wanted


async def insert_outbox_rows(
    conn,
    schema: str,
    count: int,
    *,
    event_type: str = "VisitCompleted",
    start: datetime | None = None,
) -> list[uuid.UUID]:
    """Insert unpublished outbox rows, one microsecond apart, oldest first."""
    if schema not in ("visits", "billing"):
        raise ValueError(schema)
    base = start or datetime.now(UTC)
    ids = [uuid.uuid7() for _ in range(count)]
    await conn.executemany(
        f"INSERT INTO {schema}.outbox (event_id, event_type, schema_version, payload, occurred_at)"
        " VALUES ($1, $2, 1, $3::jsonb, $4)",
        [
            (event_id, event_type, json.dumps({"n": n}), base + timedelta(microseconds=n))
            for n, event_id in enumerate(ids)
        ],
    )
    return ids


async def flush_outbox(relay, max_passes: int = 50) -> None:
    """Run passes until the relay selects nothing, so a test starts from an empty backlog."""
    for _ in range(max_passes):
        if (await relay.run_once()).selected == 0:
            return
    raise AssertionError(f"outbox backlog not empty after {max_passes} passes")


async def wait_until(predicate, timeout: float = EVENTUAL_TIMEOUT_S, message: str = "") -> None:
    deadline = time.monotonic() + timeout
    while not await predicate():
        if time.monotonic() > deadline:
            raise AssertionError(message or f"condition not met in {timeout} s")
        await asyncio.sleep(POLL_INTERVAL_S)


class RestartableRabbit:
    """A RabbitMQ container on a fixed host port, stopped and started without removal, so
    clients reconnect to the same address (module-04 task 3.1.6)."""

    def __init__(self, container, url: str) -> None:
        self.container = container
        self.url = url

    def stop(self) -> None:
        self.container.get_wrapped_container().stop(timeout=5)

    def start(self) -> None:
        self.container.get_wrapped_container().start()

    async def wait_ready(self, timeout: float = 60.0) -> None:
        import aio_pika

        deadline = time.monotonic() + timeout
        while True:
            try:
                connection = await aio_pika.connect(self.url)
                await connection.close()
                return
            except Exception:
                if time.monotonic() > deadline:
                    raise
                await asyncio.sleep(0.5)


async def connected_broker(rabbitmq_url: str, *, declare: bool = True):
    """A FastStream broker as the worker builds it: confirms on, returns raise (DL-20)."""
    from faststream.rabbit import RabbitBroker
    from faststream.rabbit.schemas import Channel

    from app.outbox.topology import declare_topology

    broker = RabbitBroker(rabbitmq_url, default_channel=Channel(on_return_raises=True))
    await broker.connect()
    if declare:
        await declare_topology(broker)
    return broker


SESSION_QUEUES = ("billing.inbox", "visits.inbox", "billing.parking", "visits.parking")


async def purge_queues(rabbitmq_url: str, queues: tuple[str, ...] = SESSION_QUEUES) -> None:
    """Drop every message in the given queues; a queue that does not exist yet is skipped
    (contract DL-27)."""
    import aio_pika

    connection = await aio_pika.connect(rabbitmq_url)
    async with connection:
        for name in queues:
            channel = await connection.channel()
            try:
                queue = await channel.declare_queue(name, passive=True)
            except aio_pika.exceptions.ChannelNotFoundEntity:
                continue
            await queue.purge()


async def start_billing_consumer(rabbitmq_url: str, sessions):
    """The Billing subscriber in the test process, wired as the worker wires it."""
    from app.billing.consumer import register

    broker = await connected_broker(rabbitmq_url)
    register(broker, sessions)
    await broker.start()
    return broker


async def publish_raw(
    rabbitmq_url: str, body: bytes, *, routing_key: str, message_id: str | None = None
) -> str:
    """Publish a message on jiris.events as another service would, with a confirm."""
    import aio_pika

    message_id = message_id or str(uuid.uuid7())
    connection = await aio_pika.connect(rabbitmq_url)
    async with connection:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        exchange = await channel.get_exchange("jiris.events", ensure=True)
        await exchange.publish(
            aio_pika.Message(
                body,
                message_id=message_id,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key,
            mandatory=True,
        )
    return message_id


async def wait_for_consumers(rabbitmq_url: str, queues: tuple[str, ...], timeout: float) -> bool:
    """True once every queue has at least one consumer (TDD section 11 readiness)."""
    import aio_pika

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            connection = await aio_pika.connect(rabbitmq_url)
            async with connection:
                channel = await connection.channel()
                counts = []
                for name in queues:
                    queue = await channel.declare_queue(name, passive=True)
                    counts.append(queue.declaration_result.consumer_count)
                if all(count > 0 for count in counts):
                    return True
        except aio_pika.exceptions.ChannelClosed:
            pass  # queues not declared yet
        await asyncio.sleep(0.2)
    return False


async def consumer_counts(rabbitmq_url: str, queues: tuple[str, ...]) -> dict[str, int]:
    """Consumers per queue; a queue that does not exist yet counts as 0."""
    import aio_pika

    counts: dict[str, int] = {}
    connection = await aio_pika.connect(rabbitmq_url)
    async with connection:
        for name in queues:
            channel = await connection.channel()
            try:
                queue = await channel.declare_queue(name, passive=True)
            except aio_pika.exceptions.ChannelNotFoundEntity:
                counts[name] = 0
                continue
            counts[name] = queue.declaration_result.consumer_count
    return counts


async def start_visits_consumer(rabbitmq_url: str, sessions):
    """The Visits subscriber in the test process, wired as the worker wires it."""
    from app.visits.consumer import register

    broker = await connected_broker(rabbitmq_url)
    register(broker, sessions)
    await broker.start()
    return broker


async def pending_visit(client: httpx.AsyncClient) -> tuple[str, str]:
    """A visit with an accepted /complete: (visit_id, completion_attempt_id)."""
    visit = await create_visit(client)
    response = await client.post(f"/api/visits/{visit['id']}/complete")
    assert response.status_code == 202, response.text
    return visit["id"], response.json()["completion_attempt_id"]


def billing_reply(
    visit_id: str,
    attempt_id: str,
    *,
    failed: bool = False,
    reason: str = "rate rejected",
    record_id: uuid.UUID | None = None,
):
    """A crafted Billing reply envelope for the Visits consumer (module-06 tests)."""
    from app.contracts import (
        BILLING_FAILED,
        BILLING_RECORD_CREATED,
        BillingFailed,
        BillingRecordCreated,
        new_envelope,
    )
    from decimal import Decimal

    if failed:
        return new_envelope(
            BILLING_FAILED,
            BillingFailed(
                visit_id=uuid.UUID(visit_id),
                completion_attempt_id=uuid.UUID(attempt_id),
                reason=reason,
                error_class="permanent",
            ),
        )
    return new_envelope(
        BILLING_RECORD_CREATED,
        BillingRecordCreated(
            visit_id=uuid.UUID(visit_id),
            completion_attempt_id=uuid.UUID(attempt_id),
            billing_record_id=record_id or uuid.uuid7(),
            amount=Decimal("50.00"),
        ),
    )


class failing_insert_trigger:
    """Make every INSERT of a billing record for one visit raise P0001 (a transient,
    unclassified error), as jiris_migrator, for the duration of a test (module-07)."""

    def __init__(self, stack: Stack, visit_id) -> None:
        self._dsn = stack.env["MIGRATIONS_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
        self._visit_id = str(visit_id)
        self._name = f"m07_fail_{uuid.uuid4().hex[:12]}"

    async def __aenter__(self) -> "failing_insert_trigger":
        import asyncpg

        self._conn = await asyncpg.connect(self._dsn)
        await self._conn.execute(
            f"CREATE FUNCTION billing.{self._name}() RETURNS trigger LANGUAGE plpgsql AS"
            " $$ BEGIN RAISE EXCEPTION 'injected failure for the M07 test'; END $$"
        )
        await self._conn.execute(
            f"CREATE TRIGGER {self._name} BEFORE INSERT ON billing.billing_record FOR EACH ROW"
            f" WHEN (NEW.visit_id = '{self._visit_id}'::uuid) EXECUTE FUNCTION billing.{self._name}()"
        )
        return self

    async def drop(self) -> None:
        await self._conn.execute(f"DROP TRIGGER IF EXISTS {self._name} ON billing.billing_record")
        await self._conn.execute(f"DROP FUNCTION IF EXISTS billing.{self._name}()")

    async def __aexit__(self, *exc: object) -> None:
        try:
            await self.drop()
        finally:
            await self._conn.close()


def start_worker_process(env: dict[str, str], log_path) -> "subprocess.Popen":
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    with open(log_path, "ab") as log:  # the child keeps its own copy of the handle
        return subprocess.Popen(
            [sys.executable, "-m", "app.main_worker"],
            cwd=root,
            env={**os.environ, **env},
            stdout=log,
            stderr=subprocess.STDOUT,
        )


async def stop_worker_process(process, timeout: float = 10.0) -> int:
    import signal

    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
    try:
        return await asyncio.to_thread(process.wait, timeout)
    except Exception:
        process.kill()
        process.wait(timeout)
        raise
