"""T8, creation validation part (PRD section 8; FR11, D11, D24; contract DL-12, DL-13).

The amount calculation part of T8 arrives with the Billing consumer (M05).
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.visits.api import VisitCreate

VALID = {
    "start_date_time": "2026-11-11T09:00:00Z",
    "end_date_time": "2026-11-11T11:00:00Z",
    "description": "Morning care visit",
    "rate": "25.00",
}


def test_valid_payload_is_accepted() -> None:
    visit = VisitCreate.model_validate(VALID)
    assert visit.rate == Decimal("25.00")


@pytest.mark.parametrize("rate", ["0", "0.00", "-1.00"])
def test_t8_non_positive_rate_is_rejected(rate: str) -> None:
    with pytest.raises(ValidationError):
        VisitCreate.model_validate({**VALID, "rate": rate})


@pytest.mark.parametrize(
    "end",
    [
        pytest.param("2026-11-11T09:00:00Z", id="equal"),
        pytest.param("2026-11-11T08:59:59Z", id="before"),
    ],
)
def test_t8_end_not_after_start_is_rejected(end: str) -> None:
    with pytest.raises(ValidationError):
        VisitCreate.model_validate({**VALID, "end_date_time": end})


def test_rate_with_more_than_two_places_is_rejected() -> None:
    """DL-12: numeric(12,2) would round silently; reject instead."""
    with pytest.raises(ValidationError):
        VisitCreate.model_validate({**VALID, "rate": "25.001"})


def test_rate_beyond_numeric_12_2_is_rejected() -> None:
    """numeric(12,2) holds at most 10 integer digits."""
    VisitCreate.model_validate({**VALID, "rate": "9999999999.99"})
    with pytest.raises(ValidationError):
        VisitCreate.model_validate({**VALID, "rate": "10000000000.00"})


def test_unknown_fields_are_rejected() -> None:
    """DL-12."""
    with pytest.raises(ValidationError):
        VisitCreate.model_validate({**VALID, "status": "Completed"})


@pytest.mark.parametrize("field", ["start_date_time", "end_date_time"])
def test_naive_timestamps_are_rejected(field: str) -> None:
    """DL-13: a time without a zone is ambiguous."""
    with pytest.raises(ValidationError):
        VisitCreate.model_validate({**VALID, field: "2026-11-11T10:00:00"})

