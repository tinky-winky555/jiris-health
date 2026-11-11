"""TD-7 (module-08 task 3.1.8; TDD section 7): BillingFailed.reason is a stable code; the raw
exception text goes to billing.inbox.last_error only."""

import asyncpg
import pytest
from sqlalchemy.exc import DBAPIError

from app.billing.service import (
    REASON_CODES,
    PermanentError,
    describe,
    failure_reason,
)


def _wrapped(orig: BaseException) -> DBAPIError:
    return DBAPIError("INSERT ...", None, orig)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        pytest.param(PermanentError("non-positive duration 0:00:00"), "invalid_payload", id="payload"),
        pytest.param(_wrapped(asyncpg.NumericValueOutOfRangeError("numeric field overflow")), "amount_out_of_range", id="22003"),
        pytest.param(_wrapped(asyncpg.InvalidTextRepresentationError("bad text")), "invalid_data", id="22P02"),
        pytest.param(_wrapped(asyncpg.CheckViolationError("check")), "constraint_violation", id="23514"),
        pytest.param(_wrapped(asyncpg.NotNullViolationError("null")), "constraint_violation", id="23502"),
    ],
)
def test_permanent_errors_map_to_stable_codes(error: BaseException, code: str) -> None:
    assert failure_reason(error, "permanent") == code


def test_exhausted_transient_errors_have_one_code() -> None:
    assert failure_reason(RuntimeError("timeout"), "transient_exhausted") == "transient_errors_exhausted"


def test_codes_are_the_documented_set() -> None:
    assert REASON_CODES == {
        "invalid_payload",
        "amount_out_of_range",
        "invalid_data",
        "constraint_violation",
        "transient_errors_exhausted",
    }


def test_the_raw_text_stays_in_describe_only() -> None:
    error = _wrapped(asyncpg.NumericValueOutOfRangeError("numeric field overflow"))
    assert "numeric field overflow" in describe(error)
    assert "overflow" not in failure_reason(error, "permanent")
