"""Parsing of a visits.inbox message (module-06 task 4.1.2; R9; contract DL-31).

Only a BillingRecordCreated or BillingFailed envelope of schema version 1 with a valid payload
is accepted; anything else is malformed and goes to visits.parking at once.
"""

import json
import uuid

import pytest

from app.outbox.consumer import MalformedMessage
from app.visits.consumer import parse_billing_reply


def _envelope(event_type: str = "BillingRecordCreated", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"visit_id": str(uuid.uuid7()), "completion_attempt_id": str(uuid.uuid7())}
    if event_type == "BillingRecordCreated":
        payload |= {"billing_record_id": str(uuid.uuid7()), "amount": "50.00"}
    else:
        payload |= {"reason": "rate rejected", "error_class": "permanent"}
    envelope: dict[str, object] = {
        "event_id": str(uuid.uuid7()),
        "event_type": event_type,
        "schema_version": 1,
        "occurred_at": "2026-11-11T10:15:00Z",
        "payload": payload,
    }
    envelope.update(overrides)
    return envelope


@pytest.mark.parametrize("event_type", ["BillingRecordCreated", "BillingFailed"])
def test_both_reply_types_are_parsed(event_type: str) -> None:
    raw = _envelope(event_type)
    envelope = parse_billing_reply(json.dumps(raw).encode())
    assert envelope.event_type == event_type
    assert str(envelope.event_id) == raw["event_id"]
    assert type(envelope.payload).__name__ == event_type


def _with_payload(event_type: str, **changes: object) -> bytes:
    raw = _envelope(event_type)
    raw["payload"] = {**raw["payload"], **changes}  # type: ignore[dict-item]
    return json.dumps(raw).encode()


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"not json", id="not-json"),
        pytest.param(b"", id="empty"),
        pytest.param(b'{"x": 1}', id="no-envelope-fields"),
        pytest.param(json.dumps(_envelope(payload={"n": 1})).encode(), id="payload-n-1"),
        pytest.param(json.dumps(_envelope("VisitCompleted")).encode(), id="visit-completed"),
        pytest.param(json.dumps(_envelope(schema_version=2)).encode(), id="other-version"),
        pytest.param(_with_payload("BillingRecordCreated", amount=50.0), id="float-amount"),
        pytest.param(_with_payload("BillingFailed", error_class="other"), id="unknown-error-class"),
    ],
)
def test_malformed_reply_is_refused(body: bytes) -> None:
    with pytest.raises(MalformedMessage):
        parse_billing_reply(body)
