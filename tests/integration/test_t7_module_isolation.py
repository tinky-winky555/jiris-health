"""T7: module isolation (PRD section 8; NFR3, D5, D13, D29).

Each application role is refused access to the other module's schema, holds
DML only on its own schema, and import-linter keeps the code boundary.
"""

import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from tests.integration.helpers import Stack

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]

FOREIGN_TABLES = [
    pytest.param("visits", "billing.billing_record", id="visits_app-on-billing.billing_record"),
    pytest.param("visits", "billing.outbox", id="visits_app-on-billing.outbox"),
    pytest.param("visits", "billing.inbox", id="visits_app-on-billing.inbox"),
    pytest.param("billing", "visits.visit", id="billing_app-on-visits.visit"),
    pytest.param("billing", "visits.outbox", id="billing_app-on-visits.outbox"),
    pytest.param("billing", "visits.inbox", id="billing_app-on-visits.inbox"),
]


def _dsn(stack: Stack, module: str) -> str:
    return stack.visits_dsn if module == "visits" else stack.billing_dsn


@pytest.mark.parametrize(("module", "table"), FOREIGN_TABLES)
async def test_t7_role_cannot_read_other_module_schema(stack: Stack, module: str, table: str) -> None:
    conn = await asyncpg.connect(_dsn(stack, module))
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch(f"SELECT 1 FROM {table} LIMIT 1")
    finally:
        await conn.close()


@pytest.mark.parametrize(
    ("module", "tables"),
    [
        pytest.param("visits", ("visits.visit", "visits.outbox", "visits.inbox"), id="visits_app"),
        pytest.param(
            "billing", ("billing.billing_record", "billing.outbox", "billing.inbox"), id="billing_app"
        ),
    ],
)
async def test_t7_role_reads_own_schema(stack: Stack, module: str, tables: tuple[str, ...]) -> None:
    conn = await asyncpg.connect(_dsn(stack, module))
    try:
        for table in tables:
            await conn.fetch(f"SELECT 1 FROM {table} LIMIT 1")
    finally:
        await conn.close()


OWN_TABLE_ROWS = {
    "visits": [
        (
            "visits.visit",
            "INSERT INTO visits.visit (id, start_date_time, end_date_time, description, rate, status)"
            " VALUES ($1, now(), now() + interval '1 hour', 'T7', 10.00, 'Scheduled')",
            "UPDATE visits.visit SET description = 'T7 updated' WHERE id = $1",
            "DELETE FROM visits.visit WHERE id = $1",
        ),
        (
            "visits.outbox",
            "INSERT INTO visits.outbox (event_id, event_type, schema_version, payload, occurred_at)"
            " VALUES ($1, 'T7', 1, '{}'::jsonb, now())",
            "UPDATE visits.outbox SET published_at = now() WHERE event_id = $1",
            "DELETE FROM visits.outbox WHERE event_id = $1",
        ),
        (
            "visits.inbox",
            "INSERT INTO visits.inbox (event_id, event_type) VALUES ($1, 'T7')",
            "UPDATE visits.inbox SET event_type = 'T7 updated' WHERE event_id = $1",
            "DELETE FROM visits.inbox WHERE event_id = $1",
        ),
    ],
    "billing": [
        (
            "billing.billing_record",
            "INSERT INTO billing.billing_record (id, visit_id, amount, status)"
            " VALUES ($1, $1, 10.00, 'Created')",
            "UPDATE billing.billing_record SET status = 'Reversed' WHERE id = $1",
            "DELETE FROM billing.billing_record WHERE id = $1",
        ),
        (
            "billing.outbox",
            "INSERT INTO billing.outbox (event_id, event_type, schema_version, payload, occurred_at)"
            " VALUES ($1, 'T7', 1, '{}'::jsonb, now())",
            "UPDATE billing.outbox SET published_at = now() WHERE event_id = $1",
            "DELETE FROM billing.outbox WHERE event_id = $1",
        ),
        (
            "billing.inbox",
            "INSERT INTO billing.inbox (event_id, event_type) VALUES ($1, 'T7')",
            "UPDATE billing.inbox SET attempts = attempts + 1 WHERE event_id = $1",
            "DELETE FROM billing.inbox WHERE event_id = $1",
        ),
    ],
}


@pytest.mark.parametrize("module", ["visits", "billing"])
async def test_t7_role_writes_own_schema(stack: Stack, module: str) -> None:
    """The role holds INSERT, UPDATE and DELETE on each of its own tables.
    Runs in a transaction that is rolled back, so no other test sees the rows.
    """
    conn = await asyncpg.connect(_dsn(stack, module))
    try:
        transaction = conn.transaction()
        await transaction.start()
        try:
            for table, insert, update, delete in OWN_TABLE_ROWS[module]:
                row_id = uuid.uuid4()
                assert await conn.execute(insert, row_id) == "INSERT 0 1", table
                assert await conn.execute(update, row_id) == "UPDATE 1", table
                assert await conn.execute(delete, row_id) == "DELETE 1", table
        finally:
            await transaction.rollback()
    finally:
        await conn.close()


@pytest.mark.parametrize("module", ["visits", "billing"])
async def test_t7_role_holds_dml_only(stack: Stack, module: str) -> None:
    """D29: application roles cannot change the schema."""
    conn = await asyncpg.connect(_dsn(stack, module))
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(f"CREATE TABLE {module}.intruder (id int)")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("CREATE TABLE public.intruder (id int)")
    finally:
        await conn.close()


ALEMBIC_VERSION_STATEMENTS = [
    pytest.param("SELECT version_num FROM {schema}.alembic_version", id="select"),
    pytest.param("INSERT INTO {schema}.alembic_version VALUES ('intruder')", id="insert"),
    pytest.param("UPDATE {schema}.alembic_version SET version_num = 'intruder'", id="update"),
    pytest.param("DELETE FROM {schema}.alembic_version", id="delete"),
]


@pytest.mark.parametrize("statement", ALEMBIC_VERSION_STATEMENTS)
@pytest.mark.parametrize("module", ["visits", "billing"])
async def test_t7_role_cannot_touch_alembic_version(
    stack: Stack, module: str, statement: str
) -> None:
    """Permanent guard (TDD section 9.1, approved by Sasha): DML is granted per table,
    so the application role has no access to its schema's migration history.
    Do not remove or relax this test.
    """
    conn = await asyncpg.connect(_dsn(stack, module))
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(statement.format(schema=module))
    finally:
        await conn.close()


def test_t7_import_linter_passes() -> None:
    result = subprocess.run(
        [str(Path(sys.executable).parent / "lint-imports")], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
