"""Event envelope and the VisitCompleted payload in app.contracts (TDD section 7; R6, D27, D28).

BillingRecordCreated and BillingFailed arrive with M05 and M06 (contract DL-14).
"""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.contracts import VISIT_COMPLETED, Envelope, EventSpec, VisitCompleted, new_envelope


def _visit_completed(rate: Decimal = Decimal("25.00")) -> VisitCompleted:
    return VisitCompleted(
        visit_id=uuid.uuid7(),
        completion_attempt_id=uuid.uuid7(),
        rate=rate,
        start_date_time=datetime(2026, 11, 11, 9, tzinfo=UTC),
        end_date_time=datetime(2026, 11, 11, 11, tzinfo=UTC),
    )


def _wire_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "visit_id": str(uuid.uuid7()),
        "completion_attempt_id": str(uuid.uuid7()),
        "rate": "25.00",
        "start_date_time": "2026-11-11T09:00:00Z",
        "end_date_time": "2026-11-11T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_visit_completed_type_routing_key_and_version_match_tdd() -> None:
    assert VISIT_COMPLETED.event_type == "VisitCompleted"
    assert VISIT_COMPLETED.routing_key == "visits.visit_completed"
    assert VISIT_COMPLETED.schema_version == 1
    assert VISIT_COMPLETED.payload_type is VisitCompleted


def test_envelope_carries_metadata_and_round_trips() -> None:
    payload = _visit_completed()
    envelope = new_envelope(VISIT_COMPLETED, payload, event_id=payload.completion_attempt_id)

    wire = json.loads(envelope.model_dump_json())
    assert set(wire) == {"event_id", "event_type", "schema_version", "occurred_at", "payload"}
    assert wire["event_id"] == str(payload.completion_attempt_id)
    assert wire["event_type"] == "VisitCompleted"
    assert wire["schema_version"] == 1
    assert wire["occurred_at"].endswith("Z")

    parsed = Envelope[VisitCompleted].model_validate_json(envelope.model_dump_json())
    assert parsed == envelope


def test_payload_wire_shape_matches_tdd() -> None:
    wire = json.loads(_visit_completed().model_dump_json())
    assert set(wire) == {
        "visit_id",
        "completion_attempt_id",
        "rate",
        "start_date_time",
        "end_date_time",
    }
    assert wire["start_date_time"] == "2026-11-11T09:00:00Z"
    assert wire["end_date_time"] == "2026-11-11T11:00:00Z"


def test_money_travels_as_two_place_decimal_string() -> None:
    assert json.loads(_visit_completed(Decimal("25.5")).model_dump_json())["rate"] == "25.50"
    assert json.loads(_visit_completed(Decimal("25")).model_dump_json())["rate"] == "25.00"


def test_money_rounds_half_up() -> None:
    assert _visit_completed(Decimal("0.125")).rate == Decimal("0.13")


def test_money_rejects_floats_on_the_wire() -> None:
    with pytest.raises(ValidationError):
        VisitCompleted.model_validate_json(json.dumps(_wire_payload(rate=25.5)))


def test_unknown_payload_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        VisitCompleted.model_validate(_wire_payload(amount="50.00"))


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError):
        VisitCompleted.model_validate(_wire_payload(start_date_time="2026-11-11T09:00:00"))


def test_new_envelope_refuses_a_payload_of_another_type() -> None:
    class Other(VisitCompleted):
        pass

    other = EventSpec("Other", "visits.other", Other)
    with pytest.raises(TypeError):
        new_envelope(other, _visit_completed())


# BillingRecordCreated (M05, contract DL-26)


def _record_created(amount: Decimal = Decimal("50.00")) -> "BillingRecordCreated":
    from app.contracts import BillingRecordCreated

    return BillingRecordCreated(
        visit_id=uuid.uuid7(),
        completion_attempt_id=uuid.uuid7(),
        billing_record_id=uuid.uuid7(),
        amount=amount,
    )


def test_billing_record_created_type_routing_key_and_version_match_tdd() -> None:
    from app.contracts import BILLING_RECORD_CREATED, EVENTS, BillingRecordCreated, routing_key_for

    assert BILLING_RECORD_CREATED.event_type == "BillingRecordCreated"
    assert BILLING_RECORD_CREATED.routing_key == "billing.record_created"
    assert BILLING_RECORD_CREATED.schema_version == 1
    assert BILLING_RECORD_CREATED.payload_type is BillingRecordCreated
    assert EVENTS["BillingRecordCreated"] is BILLING_RECORD_CREATED
    assert routing_key_for("BillingRecordCreated") == "billing.record_created"


def test_billing_record_created_wire_shape_and_money() -> None:
    wire = json.loads(_record_created(Decimal("42.5")).model_dump_json())
    assert set(wire) == {"visit_id", "completion_attempt_id", "billing_record_id", "amount"}
    assert wire["amount"] == "42.50"


def test_billing_record_created_refuses_a_float_amount() -> None:
    from app.contracts import BillingRecordCreated

    with pytest.raises(ValidationError):
        BillingRecordCreated.model_validate_json(
            json.dumps(
                {
                    "visit_id": str(uuid.uuid7()),
                    "completion_attempt_id": str(uuid.uuid7()),
                    "billing_record_id": str(uuid.uuid7()),
                    "amount": 42.5,
                }
            )
        )


def test_billing_failed_type_routing_key_and_fields_match_tdd() -> None:
    """DL-29 (reverses DL-26 for BillingFailed): registered from M06."""
    from app.contracts import BILLING_FAILED, EVENTS, BillingFailed, routing_key_for

    assert (BILLING_FAILED.event_type, BILLING_FAILED.routing_key) == ("BillingFailed", "billing.failed")
    assert BILLING_FAILED.schema_version == 1
    assert EVENTS["BillingFailed"] is BILLING_FAILED
    assert routing_key_for("BillingFailed") == "billing.failed"
    assert set(BillingFailed.model_fields) == {
        "visit_id",
        "completion_attempt_id",
        "reason",
        "error_class",
    }


@pytest.mark.parametrize("error_class", ["transient_exhausted", "permanent"])
def test_billing_failed_accepts_the_two_error_classes(error_class: str) -> None:
    from app.contracts import BillingFailed

    BillingFailed(
        visit_id=uuid.uuid7(), completion_attempt_id=uuid.uuid7(), reason="x", error_class=error_class
    )


def test_billing_failed_refuses_another_error_class() -> None:
    from app.contracts import BillingFailed

    with pytest.raises(ValidationError):
        BillingFailed(
            visit_id=uuid.uuid7(), completion_attempt_id=uuid.uuid7(), reason="x", error_class="other"
        )
