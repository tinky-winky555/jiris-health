"""Pure parts of the outbox relay and the topology (module-04 task 3.1.1; TDD sections 7, 7.1,
8.1 and 10; contract DL-18 to DL-21)."""

import itertools
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.contracts import (
    DEAD_LETTER_EXCHANGE,
    EXCHANGE,
    Envelope,
    VisitCompleted,
    format_timestamp,
    routing_key_for,
)
from app.outbox.relay import UNKNOWN_TYPE_ATTEMPT_LIMIT, OutboxRelay, backoff_delays, message_body
from app.outbox.topology import (
    BILLING_INBOX,
    BILLING_PARKING,
    INBOX_BINDINGS,
    VISITS_INBOX,
    VISITS_PARKING,
    inbox_arguments,
)


def test_backoff_starts_at_the_poll_interval_doubles_and_stops_at_30_s() -> None:
    delays = list(itertools.islice(backoff_delays(0.5, 30.0), 9))
    assert delays == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


def test_backoff_never_exceeds_a_small_ceiling() -> None:
    assert list(itertools.islice(backoff_delays(0.5, 2.0), 5)) == [0.5, 1.0, 2.0, 2.0, 2.0]


def test_exchange_names_match_tdd() -> None:
    assert (EXCHANGE, DEAD_LETTER_EXCHANGE) == ("jiris.events", "jiris.dlx")


def test_routing_key_of_visit_completed() -> None:
    assert routing_key_for("VisitCompleted") == "visits.visit_completed"


def test_unknown_event_type_has_no_routing_key() -> None:
    assert routing_key_for("NoSuchEvent") is None


def test_format_timestamp_is_utc_with_z() -> None:
    kyiv = timezone(timedelta(hours=2))
    assert format_timestamp(datetime(2026, 11, 11, 12, 15, tzinfo=kyiv)) == "2026-11-11T10:15:00Z"


def test_message_body_is_the_tdd_envelope() -> None:
    event_id = uuid.uuid7()
    payload = {
        "visit_id": str(uuid.uuid7()),
        "completion_attempt_id": str(event_id),
        "rate": "25.00",
        "start_date_time": "2026-11-11T09:00:00Z",
        "end_date_time": "2026-11-11T11:00:00Z",
    }
    row = {
        "event_id": event_id,
        "event_type": "VisitCompleted",
        "schema_version": 1,
        "occurred_at": datetime(2026, 11, 11, 10, 15, 0, 123456, tzinfo=UTC),
        "payload": payload,
    }

    body = json.loads(message_body(row))

    assert body == {
        "event_id": str(event_id),
        "event_type": "VisitCompleted",
        "schema_version": 1,
        "occurred_at": "2026-11-11T10:15:00.123456Z",
        "payload": payload,
    }
    Envelope[VisitCompleted].model_validate(body)


@pytest.mark.parametrize("schema", ["public", "visits; DROP TABLE x", "Visits", ""])
def test_relay_refuses_a_schema_other_than_visits_or_billing(schema: str) -> None:
    with pytest.raises(ValueError):
        OutboxRelay(schema=schema, engine=None, broker=None)  # type: ignore[arg-type]


def test_unknown_type_attempt_limit_is_five() -> None:
    assert UNKNOWN_TYPE_ATTEMPT_LIMIT == 5


def test_inbox_queues_dead_letter_to_their_parking_queue() -> None:
    assert inbox_arguments(BILLING_INBOX) == {
        "x-dead-letter-exchange": "jiris.dlx",
        "x-dead-letter-routing-key": BILLING_PARKING,
    }
    assert inbox_arguments(VISITS_INBOX) == {
        "x-dead-letter-exchange": "jiris.dlx",
        "x-dead-letter-routing-key": VISITS_PARKING,
    }


def test_inbox_bindings_match_tdd() -> None:
    assert INBOX_BINDINGS == {BILLING_INBOX: "visits.*", VISITS_INBOX: "billing.*"}
    assert (BILLING_PARKING, VISITS_PARKING) == ("billing.parking", "visits.parking")
