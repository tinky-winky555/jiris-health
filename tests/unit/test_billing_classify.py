"""Error classes of the Billing consumer (module-07 task 4.1.2; TDD section 8.2; D15; contract
DL-35, DL-36)."""

import asyncpg
import pytest
from sqlalchemy.exc import DBAPIError, OperationalError

from app.billing.consumer import classify
from app.billing.service import PermanentError


def _wrapped(orig: BaseException) -> DBAPIError:
    return DBAPIError("INSERT ...", None, orig)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(PermanentError("non-positive duration"), id="payload-validation"),
        pytest.param(_wrapped(asyncpg.NumericValueOutOfRangeError("overflow")), id="22003-overflow"),
        pytest.param(_wrapped(asyncpg.InvalidTextRepresentationError("bad")), id="22P02"),
        pytest.param(_wrapped(asyncpg.CheckViolationError("check")), id="23514-check"),
        pytest.param(_wrapped(asyncpg.NotNullViolationError("null")), id="23502-not-null"),
        pytest.param(_wrapped(asyncpg.ForeignKeyViolationError("fk")), id="23503-foreign-key"),
    ],
)
def test_permanent_errors(error: BaseException) -> None:
    assert classify(error) == "permanent"


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(_wrapped(asyncpg.UniqueViolationError("duplicate")), id="23505-stays-transient"),
        pytest.param(_wrapped(asyncpg.RaiseError("injected")), id="P0001-raise"),
        pytest.param(RuntimeError("bug"), id="unclassified"),
        pytest.param(ValueError("unexpected"), id="value-error"),
    ],
)
def test_transient_and_unclassified_errors(error: BaseException) -> None:
    assert classify(error) == "transient"


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ConnectionRefusedError(61, "refused"), id="connection-refused"),
        pytest.param(asyncpg.ConnectionDoesNotExistError("closed"), id="connection-lost"),
        pytest.param(OperationalError("SELECT 1", None, Exception("x")), id="operational"),
        pytest.param(TimeoutError(), id="timeout"),
        # DL-39 (TD-6): no longer counted; were transient in M07 (DL-36)
        pytest.param(_wrapped(asyncpg.DeadlockDetectedError("deadlock")), id="40P01-deadlock"),
        pytest.param(_wrapped(asyncpg.SerializationError("serialisation")), id="40001-serialisation"),
    ],
)
def test_database_unavailable(error: BaseException) -> None:
    assert classify(error) == "unavailable"


def test_permanent_error_inside_a_cause_chain() -> None:
    try:
        try:
            raise PermanentError("non-positive duration")
        except PermanentError as inner:
            raise RuntimeError("billing failed") from inner
    except RuntimeError as outer:
        assert classify(outer) == "permanent"
