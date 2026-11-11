"""Billing service on a real PostgreSQL as billing_app (module-05 tasks 4.1.3 to 4.1.6; TDD
section 8.2; T2, R8, D3, D11, NFR2)."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg
import pytest

from app.billing.service import process_visit_completed
from app.contracts import VISIT_COMPLETED, BillingRecordCreated, Envelope, VisitCompleted, new_envelope

pytestmark = pytest.mark.integration


def _visit_completed(
    visit_id: uuid.UUID | None = None, rate: str = "25.00"
) -> Envelope[VisitCompleted]:
    event_id = uuid.uuid7()
    return new_envelope(
        VISIT_COMPLETED,
        VisitCompleted(
            visit_id=visit_id or uuid.uuid7(),
            completion_attempt_id=event_id,
            rate=Decimal(rate),
            start_date_time=datetime(2026, 11, 11, 9, tzinfo=UTC),
            end_date_time=datetime(2026, 11, 11, 11, tzinfo=UTC),
        ),
        event_id=event_id,
    )


async def _process(sessions, envelope: Envelope[VisitCompleted]):
    async with sessions.begin() as session:
        return await process_visit_completed(session, envelope)


async def _records(db: asyncpg.Connection, visit_id: uuid.UUID) -> list[asyncpg.Record]:
    return await db.fetch("SELECT * FROM billing.billing_record WHERE visit_id = $1", visit_id)


async def _replies(db: asyncpg.Connection, visit_id: uuid.UUID) -> list[asyncpg.Record]:
    return await db.fetch(
        "SELECT * FROM billing.outbox WHERE payload->>'visit_id' = $1 ORDER BY occurred_at",
        str(visit_id),
    )


async def _inbox(db: asyncpg.Connection, event_id: uuid.UUID) -> list[asyncpg.Record]:
    return await db.fetch("SELECT * FROM billing.inbox WHERE event_id = $1", event_id)


# 4.1.3 One transaction: record, reply, inbox


async def test_visit_completed_creates_record_reply_and_inbox_row(
    billing_sessions, billing_db: asyncpg.Connection
) -> None:
    envelope = _visit_completed(rate="25.00")
    visit_id = envelope.payload.visit_id

    outcome = await _process(billing_sessions, envelope)

    assert outcome.duplicate is False
    [record] = await _records(billing_db, visit_id)
    assert (record["status"], record["amount"]) == ("Created", Decimal("50.00"))
    assert record["id"] == outcome.billing_record_id
    [reply] = await _replies(billing_db, visit_id)
    assert reply["event_id"] == outcome.reply_event_id
    # Not published_at: a running relay may publish the reply at any moment (DL-22).
    assert (reply["event_type"], reply["schema_version"]) == ("BillingRecordCreated", 1)
    payload = BillingRecordCreated.model_validate(json.loads(reply["payload"]))
    assert payload == BillingRecordCreated(
        visit_id=visit_id,
        completion_attempt_id=envelope.payload.completion_attempt_id,
        billing_record_id=record["id"],
        amount=Decimal("50.00"),
    )
    [inbox] = await _inbox(billing_db, envelope.event_id)
    assert (inbox["event_type"], inbox["status"], inbox["attempts"]) == ("VisitCompleted", "processed", 0)
    assert inbox["processed_at"] is not None


async def test_nothing_is_written_when_the_transaction_rolls_back(
    billing_sessions, billing_db: asyncpg.Connection
) -> None:
    envelope = _visit_completed()
    with pytest.raises(RuntimeError):
        async with billing_sessions.begin() as session:
            await process_visit_completed(session, envelope)
            raise RuntimeError("fail before COMMIT")

    assert await _records(billing_db, envelope.payload.visit_id) == []
    assert await _replies(billing_db, envelope.payload.visit_id) == []
    assert await _inbox(billing_db, envelope.event_id) == []


# 4.1.4 T2 and the idempotency test


async def test_t2_same_event_twice_gives_one_record_and_one_reply(
    billing_sessions, billing_db: asyncpg.Connection
) -> None:
    envelope = _visit_completed()

    first = await _process(billing_sessions, envelope)
    second = await _process(billing_sessions, envelope)

    assert (first.duplicate, second.duplicate) == (False, True)
    assert len(await _records(billing_db, envelope.payload.visit_id)) == 1
    assert len(await _replies(billing_db, envelope.payload.visit_id)) == 1
    assert len(await _inbox(billing_db, envelope.event_id)) == 1


# 4.1.5 Concurrent duplicate


async def test_t2_same_event_at_the_same_time_gives_one_record_and_one_reply(
    billing_sessions, billing_db: asyncpg.Connection
) -> None:
    envelope = _visit_completed()

    outcomes = await asyncio.gather(*(_process(billing_sessions, envelope) for _ in range(2)))

    assert sorted(o.duplicate for o in outcomes) == [False, True]
    assert len(await _records(billing_db, envelope.payload.visit_id)) == 1
    assert len(await _replies(billing_db, envelope.payload.visit_id)) == 1


# 4.1.6 R8: a second attempt for a visit that already has an active record


@pytest.mark.parametrize("concurrent", [False, True], ids=["sequential", "concurrent"])
async def test_r8_second_attempt_replies_with_the_existing_record(
    billing_sessions, billing_db: asyncpg.Connection, concurrent: bool
) -> None:
    visit_id = uuid.uuid7()
    first, second = _visit_completed(visit_id), _visit_completed(visit_id, rate="99.00")

    if concurrent:
        outcomes = await asyncio.gather(_process(billing_sessions, first), _process(billing_sessions, second))
    else:
        outcomes = [await _process(billing_sessions, first), await _process(billing_sessions, second)]

    assert [o.duplicate for o in outcomes] == [False, False]
    [record] = await _records(billing_db, visit_id)
    replies = [BillingRecordCreated.model_validate(json.loads(r["payload"])) for r in await _replies(billing_db, visit_id)]
    assert len(replies) == 2
    assert {r.billing_record_id for r in replies} == {record["id"]}
    assert {r.completion_attempt_id for r in replies} == {
        first.payload.completion_attempt_id,
        second.payload.completion_attempt_id,
    }
    assert {r.amount for r in replies} == {record["amount"]}  # the existing record's amount


# Regression: ON CONFLICT on the partial index under a generic plan (TDD section 8.2)


@pytest.mark.parametrize("plan_cache_mode", ["auto", "force_generic_plan"])
async def test_on_conflict_survives_the_generic_plan(
    billing_engine, billing_db: asyncpg.Connection, plan_cache_mode: str
) -> None:
    """12 attempts for one visit on one connection, so asyncpg reuses its prepared statements
    and PostgreSQL moves them to a generic plan (after five executions under `auto`, at once
    under `force_generic_plan`). Every attempt after the first conflicts on ux_active_record;
    none may raise, and one active record remains."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    visit_id = uuid.uuid7()
    attempts = 12
    async with billing_engine.connect() as conn:
        await conn.execute(text(f"SET plan_cache_mode = {plan_cache_mode}"))
        await conn.commit()
        backend = await conn.scalar(text("SELECT pg_backend_pid()"))
        outcomes = []
        for _ in range(attempts):
            async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                async with session.begin():
                    outcomes.append(await process_visit_completed(session, _visit_completed(visit_id)))
            assert await conn.scalar(text("SELECT pg_backend_pid()")) == backend  # one connection
            await conn.commit()

    assert [o.duplicate for o in outcomes] == [False] * attempts
    [record] = await billing_db.fetch(
        "SELECT * FROM billing.billing_record WHERE visit_id = $1 AND status = 'Created'", visit_id
    )
    assert {o.billing_record_id for o in outcomes} == {record["id"]}
    assert len(await _replies(billing_db, visit_id)) == attempts
