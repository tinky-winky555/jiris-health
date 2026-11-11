"""Failure classification shared by the consumers (module-06 task 4.3; contract DL-31, DL-33).

Database unavailable or connection lost is retried with backoff and never counted; anything
else is the caller's to classify.
"""

import asyncpg
import pytest
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.outbox.consumer import is_database_unavailable


def _wrapped(orig: BaseException, *, invalidated: bool = False) -> DBAPIError:
    return DBAPIError("SELECT 1", None, orig, connection_invalidated=invalidated)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ConnectionRefusedError(61, "refused"), id="connection-refused"),
        pytest.param(OSError(64, "host is down"), id="os-error"),
        pytest.param(TimeoutError(), id="timeout"),
        pytest.param(asyncpg.ConnectionDoesNotExistError("closed"), id="asyncpg-connection-lost"),
        pytest.param(asyncpg.CannotConnectNowError("starting up"), id="asyncpg-cannot-connect"),
        pytest.param(asyncpg.TooManyConnectionsError("too many"), id="asyncpg-too-many"),
        pytest.param(_wrapped(Exception("x"), invalidated=True), id="sqlalchemy-invalidated"),
        pytest.param(_wrapped(ConnectionResetError(54, "reset")), id="sqlalchemy-wraps-os-error"),
        pytest.param(OperationalError("SELECT 1", None, Exception("x")), id="sqlalchemy-operational"),
        pytest.param(InterfaceError("SELECT 1", None, Exception("x")), id="sqlalchemy-interface"),
    ],
)
def test_database_unavailable_is_recognised(error: BaseException) -> None:
    assert is_database_unavailable(error)


def test_a_cause_chain_is_followed() -> None:
    try:
        try:
            raise ConnectionRefusedError(61, "refused")
        except ConnectionRefusedError as inner:
            raise RuntimeError("connect failed") from inner
    except RuntimeError as outer:
        assert is_database_unavailable(outer)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ValueError("bad"), id="value-error"),
        pytest.param(RuntimeError("bug"), id="runtime-error"),
        pytest.param(_wrapped(asyncpg.RaiseError("injected")), id="raised-in-sql"),
        pytest.param(_wrapped(asyncpg.UniqueViolationError("duplicate")), id="unique-violation"),
        pytest.param(_wrapped(asyncpg.InsufficientPrivilegeError("denied")), id="privilege"),
    ],
)
def test_other_errors_are_not_database_unavailable(error: BaseException) -> None:
    assert not is_database_unavailable(error)


# TD-6 (module-08 task 3.1.7; DL-39): narrowed by SQLSTATE


@pytest.mark.parametrize(
    "orig",
    [
        pytest.param(asyncpg.ConnectionFailureError("lost"), id="08006"),
        pytest.param(asyncpg.AdminShutdownError("shutdown"), id="57P01"),
        pytest.param(asyncpg.CrashShutdownError("crash"), id="57P02"),
        pytest.param(asyncpg.CannotConnectNowError("starting"), id="57P03"),
        pytest.param(asyncpg.SerializationError("serialisation"), id="40001"),
        pytest.param(asyncpg.DeadlockDetectedError("deadlock"), id="40P01"),
    ],
)
def test_temporary_sqlstates_are_unavailable(orig: BaseException) -> None:
    assert is_database_unavailable(OperationalError("SELECT 1", None, orig))
    assert is_database_unavailable(_wrapped(orig))


@pytest.mark.parametrize(
    "orig",
    [
        pytest.param(asyncpg.DivisionByZeroError("zero"), id="22012"),
        pytest.param(asyncpg.InternalServerError("internal"), id="XX000"),
        pytest.param(asyncpg.RaiseError("raised"), id="P0001"),
    ],
)
def test_operational_error_with_another_sqlstate_is_counted(orig: BaseException) -> None:
    assert not is_database_unavailable(OperationalError("SELECT 1", None, orig))
