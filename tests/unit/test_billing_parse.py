"""Parsing of a billing.inbox message (module-05 task 4.1.8 at unit level; R9; contract DL-25).

Anything that is not a valid VisitCompleted envelope, schema version 1, is malformed and goes
to billing.parking without a retry.
"""

import json
import uuid

import pytest

from app.billing.consumer import MalformedMessage, parse_visit_completed


def _envelope(**overrides: object) -> dict[str, object]:
    event_id = str(uuid.uuid7())
    envelope: dict[str, object] = {
        "event_id": event_id,
        "event_type": "VisitCompleted",
        "schema_version": 1,
        "occurred_at": "2026-11-11T10:15:00Z",
        "payload": {
            "visit_id": str(uuid.uuid7()),
            "completion_attempt_id": event_id,
            "rate": "25.00",
            "start_date_time": "2026-11-11T09:00:00Z",
            "end_date_time": "2026-11-11T11:00:00Z",
        },
    }
    envelope.update(overrides)
    return envelope


def test_valid_envelope_is_parsed() -> None:
    raw = _envelope()
    envelope = parse_visit_completed(json.dumps(raw).encode())
    assert str(envelope.event_id) == raw["event_id"]
    assert str(envelope.payload.rate) == "25.00"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"not json", id="not-json"),
        pytest.param(b'{"x": 1}', id="no-envelope-fields"),
        pytest.param(json.dumps(_envelope(payload={"n": 1})).encode(), id="payload-n-1"),
        pytest.param(json.dumps(_envelope(event_type="VisitStarted")).encode(), id="other-type"),
        pytest.param(json.dumps(_envelope(schema_version=2)).encode(), id="other-version"),
        pytest.param(
            json.dumps(
                _envelope(
                    payload={
                        "visit_id": str(uuid.uuid7()),
                        "completion_attempt_id": str(uuid.uuid7()),
                        "rate": "25.00",
                        "start_date_time": "2026-11-11T09:00:00",
                        "end_date_time": "2026-11-11T11:00:00",
                    }
                )
            ).encode(),
            id="naive-timestamps",
        ),
        pytest.param(b"", id="empty"),
    ],
)
def test_malformed_message_is_refused(body: bytes) -> None:
    with pytest.raises(MalformedMessage):
        parse_visit_completed(body)
