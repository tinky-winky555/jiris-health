"""Event envelope and payload models shared by Visits and Billing (TDD section 7; D20, D27).

Imports nothing from app.visits or app.billing (import-linter). M03 defines the
envelope and VisitCompleted; the Billing replies arrive with M05 and M06 (contract DL-14).
M04 adds the exchange names and the event type to routing key registry (DL-21).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
)

EXCHANGE = "jiris.events"  # topic exchange of every event (TDD section 7.1)
DEAD_LETTER_EXCHANGE = "jiris.dlx"  # direct exchange to the parking queues (DL-18)

CENT = Decimal("0.01")


def to_money(value: Decimal) -> Decimal:
    """Two decimal places, ROUND_HALF_UP (D11)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("money must be a decimal string, not a float")
    return value


def _money_text(value: Decimal) -> str:
    return str(value)


def format_timestamp(value: datetime) -> str:
    """UTC with a Z suffix, the wire form of every timestamp (TDD section 7)."""
    return value.astimezone(UTC).isoformat().removesuffix("+00:00") + "Z"


# Money is a Decimal in code and a decimal string such as "42.50" on the wire (D28).
# Floats are refused so that no binary rounding can enter an event.
Money = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    AfterValidator(to_money),
    PlainSerializer(_money_text, return_type=str, when_used="json"),
]

# Timestamps carry a time zone and travel as UTC with a Z suffix.
Timestamp = Annotated[AwareDatetime, PlainSerializer(format_timestamp, return_type=str, when_used="json")]


class Payload(BaseModel):
    """Base of every event payload: immutable, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class VisitCompleted(Payload):
    """Visits to Billing: one accepted /complete (FR1); attempt id = event id (R1)."""

    visit_id: uuid.UUID
    completion_attempt_id: uuid.UUID
    rate: Money
    start_date_time: Timestamp
    end_date_time: Timestamp


class Envelope[P: Payload](BaseModel):
    """Common envelope of every event (R6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: uuid.UUID
    event_type: str
    schema_version: int
    occurred_at: Timestamp
    payload: P


@dataclass(frozen=True)
class EventSpec[P: Payload]:
    """Event type, routing key (TDD section 7) and payload model of one event."""

    event_type: str
    routing_key: str
    payload_type: type[P]
    schema_version: int = 1


VISIT_COMPLETED = EventSpec("VisitCompleted", "visits.visit_completed", VisitCompleted)

# Every event the system can publish, by event type. The outbox relay routes only these.
EVENTS: dict[str, EventSpec] = {spec.event_type: spec for spec in (VISIT_COMPLETED,)}


def routing_key_for(event_type: str) -> str | None:
    """Routing key of a known event type, or None when the type is not registered."""
    spec = EVENTS.get(event_type)
    return spec.routing_key if spec else None


def new_envelope[P: Payload](
    spec: EventSpec[P],
    payload: P,
    *,
    event_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
) -> Envelope[P]:
    if not isinstance(payload, spec.payload_type):
        raise TypeError(f"{spec.event_type} expects {spec.payload_type.__name__}")
    return Envelope[spec.payload_type](
        event_id=event_id or uuid.uuid7(),
        event_type=spec.event_type,
        schema_version=spec.schema_version,
        occurred_at=occurred_at or datetime.now(UTC),
        payload=payload,
    )


__all__ = [
    "DEAD_LETTER_EXCHANGE",
    "EVENTS",
    "EXCHANGE",
    "VISIT_COMPLETED",
    "Envelope",
    "EventSpec",
    "Money",
    "Payload",
    "Timestamp",
    "VisitCompleted",
    "format_timestamp",
    "new_envelope",
    "routing_key_for",
    "to_money",
]
