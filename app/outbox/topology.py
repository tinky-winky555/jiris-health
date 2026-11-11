"""RabbitMQ topology of TDD section 7.1 (D8, D20; contract DL-18, DL-21).

Declared by the worker at start; declaring again is harmless. The M05 and M06
consumers subscribe with the queue objects defined here, so that every client
declares the queues with the same arguments. Imports neither module.
"""

from typing import Any

from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from app.contracts import DEAD_LETTER_EXCHANGE, EXCHANGE

BILLING_INBOX = "billing.inbox"
VISITS_INBOX = "visits.inbox"
BILLING_PARKING = "billing.parking"
VISITS_PARKING = "visits.parking"

EVENTS_EXCHANGE = RabbitExchange(EXCHANGE, type=ExchangeType.TOPIC, durable=True)
PARKING_EXCHANGE = RabbitExchange(DEAD_LETTER_EXCHANGE, type=ExchangeType.DIRECT, durable=True)

# Each consuming module reads the events of the other one.
INBOX_BINDINGS = {BILLING_INBOX: "visits.*", VISITS_INBOX: "billing.*"}
PARKING_OF = {BILLING_INBOX: BILLING_PARKING, VISITS_INBOX: VISITS_PARKING}


def inbox_arguments(inbox: str) -> dict[str, Any]:
    """Dead letters go to the module's parking queue by an explicit routing key (DL-18)."""
    return {
        "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
        "x-dead-letter-routing-key": PARKING_OF[inbox],
    }


INBOX_QUEUES = {
    name: RabbitQueue(name, durable=True, arguments=inbox_arguments(name)) for name in INBOX_BINDINGS
}
PARKING_QUEUES = {name: RabbitQueue(name, durable=True) for name in PARKING_OF.values()}


async def declare_topology(broker: RabbitBroker) -> None:
    events = await broker.declare_exchange(EVENTS_EXCHANGE)
    parking = await broker.declare_exchange(PARKING_EXCHANGE)
    for name, pattern in INBOX_BINDINGS.items():
        queue = await broker.declare_queue(INBOX_QUEUES[name])
        await queue.bind(events, routing_key=pattern)
    for name, queue_spec in PARKING_QUEUES.items():
        queue = await broker.declare_queue(queue_spec)
        await queue.bind(parking, routing_key=name)
