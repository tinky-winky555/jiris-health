"""RabbitMQ topology (module-04 task 3.1.2; TDD section 7.1; D8, D20; contract DL-18, DL-21)."""

import uuid

import aio_pika
import pytest

from tests.integration.helpers import Stack, collect_messages

pytestmark = pytest.mark.integration

QUEUES = ("billing.inbox", "visits.inbox", "billing.parking", "visits.parking")


async def _publish(rabbitmq_url: str, routing_key: str) -> str:
    message_id = str(uuid.uuid7())
    connection = await aio_pika.connect(rabbitmq_url)
    async with connection:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        exchange = await channel.get_exchange("jiris.events", ensure=True)
        await exchange.publish(
            aio_pika.Message(b"{}", message_id=message_id), routing_key=routing_key, mandatory=True
        )
    return message_id


async def test_declare_topology_is_idempotent(events_broker, stack: Stack) -> None:
    from app.outbox.topology import declare_topology

    await declare_topology(events_broker)
    await declare_topology(events_broker)

    connection = await aio_pika.connect(stack.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        for name in ("jiris.events", "jiris.dlx"):
            await channel.get_exchange(name, ensure=True)
        for name in QUEUES:
            await channel.declare_queue(name, passive=True)


async def test_queues_and_exchanges_are_durable(events_broker, stack: Stack) -> None:
    """Redeclaring with durable=False is refused when the object exists as durable."""
    for kind, name in [("queue", q) for q in QUEUES] + [
        ("exchange", "jiris.events"),
        ("exchange", "jiris.dlx"),
    ]:
        connection = await aio_pika.connect(stack.rabbitmq_url)
        async with connection:
            channel = await connection.channel()
            with pytest.raises(aio_pika.exceptions.ChannelPreconditionFailed):
                if kind == "queue":
                    await channel.declare_queue(name, durable=False)
                else:
                    exchange_type = "topic" if name == "jiris.events" else "direct"
                    await channel.declare_exchange(name, exchange_type, durable=False)


@pytest.mark.parametrize(
    ("routing_key", "queue", "other"),
    [
        pytest.param("visits.visit_completed", "billing.inbox", "visits.inbox", id="visit_completed"),
        pytest.param("billing.record_created", "visits.inbox", "billing.inbox", id="record_created"),
        pytest.param("billing.failed", "visits.inbox", "billing.inbox", id="failed"),
    ],
)
async def test_routing_keys_reach_the_consuming_module_only(
    events_broker, stack: Stack, routing_key: str, queue: str, other: str
) -> None:
    message_id = await _publish(stack.rabbitmq_url, routing_key)

    [delivered] = await collect_messages(stack.rabbitmq_url, queue, {message_id})
    assert delivered.routing_key == routing_key
    assert await collect_messages(stack.rabbitmq_url, other, {message_id}, timeout=1.0) == []


@pytest.mark.parametrize(
    ("routing_key", "inbox", "parking"),
    [
        pytest.param("visits.visit_completed", "billing.inbox", "billing.parking", id="billing"),
        pytest.param("billing.failed", "visits.inbox", "visits.parking", id="visits"),
    ],
)
async def test_rejected_message_reaches_its_parking_queue(
    events_broker, stack: Stack, routing_key: str, inbox: str, parking: str
) -> None:
    message_id = await _publish(stack.rabbitmq_url, routing_key)
    await collect_messages(stack.rabbitmq_url, inbox, {message_id}, reject=True)

    [parked] = await collect_messages(stack.rabbitmq_url, parking, {message_id})

    assert parked.routing_key == parking  # DL-18: explicit dead-letter routing key
    [death] = parked.headers["x-death"]
    assert death["queue"] == inbox
    assert death["reason"] == "rejected"
    assert list(death["routing-keys"]) == [routing_key]
