"""T8, amount calculation part (PRD section 8; FR5, D11; module-05 task 4.1.1).

amount = rate x hours(end - start), in Decimal from the exact duration, 2 places, ROUND_HALF_UP.
"""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.billing.service import compute_amount

START = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("rate", "duration", "amount"),
    [
        pytest.param("25.00", timedelta(hours=2), "50.00", id="whole-hours"),
        pytest.param("10.00", timedelta(hours=1, minutes=20), "13.33", id="third-of-an-hour"),
        pytest.param("0.01", timedelta(minutes=30), "0.01", id="half-up-not-half-even"),
        pytest.param("33.33", timedelta(minutes=30), "16.67", id="half-up-at-the-cent"),
        pytest.param("19.99", timedelta(minutes=45), "14.99", id="three-quarters"),
        pytest.param("60.00", timedelta(seconds=1), "0.02", id="one-second"),
        pytest.param("36.00", timedelta(microseconds=500_000), "0.01", id="half-a-second-half-up"),
        pytest.param("9999999999.99", timedelta(minutes=6), "1000000000.00", id="large-rate"),
    ],
)
def test_t8_amount_is_decimal_two_places_half_up(rate: str, duration: timedelta, amount: str) -> None:
    result = compute_amount(Decimal(rate), START, START + duration)
    assert isinstance(result, Decimal)
    assert result == Decimal(amount)
    assert str(result) == amount  # exactly two places


def test_amount_uses_the_exact_duration_across_days() -> None:
    assert compute_amount(Decimal("1.00"), START, START + timedelta(days=1, hours=1)) == Decimal("25.00")


def test_amount_does_not_depend_on_the_time_zone_of_the_inputs() -> None:
    plus_two = START.astimezone(timezone(timedelta(hours=2)))
    assert compute_amount(Decimal("25.00"), plus_two, START + timedelta(hours=2)) == Decimal("50.00")


def test_amount_refuses_a_float_rate() -> None:
    with pytest.raises(TypeError):
        compute_amount(25.0, START, START + timedelta(hours=2))  # type: ignore[arg-type]
