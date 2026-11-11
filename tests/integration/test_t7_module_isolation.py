"""T7: module isolation (PRD section 8; NFR3, D5, D13, D29).

Each application role is refused access to the other module's schema, holds
DML only on its own schema, and import-linter keeps the code boundary.
"""

import subprocess
import sys
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
