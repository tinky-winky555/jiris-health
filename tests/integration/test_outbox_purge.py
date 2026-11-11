"""Outbox purge (module-08 task 3.1.1; R5, D25, NFR7; TDD section 8.1): published rows older than
7 days go; unpublished rows never do; each schema as its own role."""

import json
import uuid
from datetime import timedelta

import asyncpg
import pytest

from app.outbox.purge import OutboxPurge

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_foreign_consumers")]  # DL-32


async def _insert(conn: asyncpg.Connection, schema: str, *, published_ago, occurred_ago, attempts=0) -> uuid.UUID:
    event_id = uuid.uuid7()
    await conn.execute(
        f"INSERT INTO {schema}.outbox (event_id, event_type, schema_version, payload, occurred_at,"
        " published_at, attempts)"
        " VALUES ($1, 'VisitCompleted', 1, $2::jsonb, now() - $3::interval,"
        " CASE WHEN $4::interval IS NULL THEN NULL ELSE now() - $4::interval END, $5)",
        event_id,
        json.dumps({"purge": True}),
        occurred_ago,
        published_ago,
        attempts,
    )
    return event_id


async def _exists(conn: asyncpg.Connection, schema: str, event_id: uuid.UUID) -> bool:
    return bool(await conn.fetchval(f"SELECT count(*) FROM {schema}.outbox WHERE event_id = $1", event_id))


@pytest.mark.parametrize("schema", ["visits", "billing"])
async def test_purge_deletes_only_published_rows_older_than_seven_days(
    visits_db, billing_db, visits_engine, billing_engine, schema: str
) -> None:
    conn = visits_db if schema == "visits" else billing_db
    engine = visits_engine if schema == "visits" else billing_engine
    day = timedelta(days=1)
    old = await _insert(conn, schema, published_ago=8 * day, occurred_ago=8 * day)
    just_old = await _insert(conn, schema, published_ago=7 * day + timedelta(minutes=1), occurred_ago=8 * day)
    recent = await _insert(conn, schema, published_ago=7 * day - timedelta(minutes=1), occurred_ago=8 * day)
    unpublished = await _insert(conn, schema, published_ago=None, occurred_ago=30 * day)
    excluded = await _insert(conn, schema, published_ago=None, occurred_ago=30 * day, attempts=5)
    try:
        deleted = await OutboxPurge(schema=schema, engine=engine).run_once()

        assert deleted >= 2
        assert not await _exists(conn, schema, old)
        assert not await _exists(conn, schema, just_old)
        assert await _exists(conn, schema, recent)
        assert await _exists(conn, schema, unpublished)
        assert await _exists(conn, schema, excluded)
        assert await OutboxPurge(schema=schema, engine=engine).run_once() == 0
    finally:
        await conn.execute(
            f"DELETE FROM {schema}.outbox WHERE event_id = ANY($1::uuid[])",
            [recent, unpublished, excluded],
        )


async def test_purge_works_in_batches(visits_db, visits_engine) -> None:
    ids = [
        await _insert(visits_db, "visits", published_ago=timedelta(days=10), occurred_ago=timedelta(days=10))
        for _ in range(25)
    ]
    purge = OutboxPurge(schema="visits", engine=visits_engine, batch_size=10)

    assert await purge.run_once() == 25
    assert await visits_db.fetchval("SELECT count(*) FROM visits.outbox WHERE event_id = ANY($1::uuid[])", ids) == 0


@pytest.mark.parametrize("schema", ["public", "visits; DROP TABLE x", ""])
def test_purge_refuses_another_schema(schema: str) -> None:
    with pytest.raises(ValueError):
        OutboxPurge(schema=schema, engine=None)  # type: ignore[arg-type]
