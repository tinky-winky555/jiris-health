"""Billing replies applied by the Visits service (module-06 tasks 4.1.3 to 4.1.8; TDD section 6.4;
R1, R3, D16, D23, FR6, FR8, FR9; T6; contract DL-29 to DL-31)."""

import asyncio
import logging
import uuid

import asyncpg
import pytest

from app.visits.service import UnknownVisit, apply_billing_reply
from tests.integration.helpers import billing_reply, create_visit, pending_visit, start_visit

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_foreign_consumers")]  # DL-32


async def _apply(sessions, envelope):
    async with sessions.begin() as session:
        return await apply_billing_reply(session, envelope)


async def _visit(client, visit_id: str) -> dict:
    response = await client.get(f"/api/visits/{visit_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def _inbox(db: asyncpg.Connection, event_id: uuid.UUID) -> asyncpg.Record | None:
    return await db.fetchrow("SELECT * FROM visits.inbox WHERE event_id = $1", event_id)


# 4.1.3 BillingRecordCreated for the current attempt


async def test_record_created_completes_the_visit(
    make_client, visits_sessions, visits_db: asyncpg.Connection
) -> None:
    client = make_client()
    visit_id, attempt = await pending_visit(client)
    before = await _visit(client, visit_id)
    reply = billing_reply(visit_id, attempt)

    outcome = await _apply(visits_sessions, reply)

    assert outcome.kind == "completed"
    visit = await _visit(client, visit_id)
    assert (visit["status"], visit["completion_pending"]) == ("Completed", False)
    assert visit["completion_requested_at"] == before["completion_requested_at"]  # D23
    inbox = await _inbox(visits_db, reply.event_id)
    assert (inbox["event_type"], inbox["attempts"], inbox["last_error"]) == (
        "BillingRecordCreated",
        0,
        None,
    )
    assert inbox["processed_at"] is not None


# 4.1.4 Idempotency


async def test_the_same_reply_twice_changes_nothing(
    make_client, visits_sessions, visits_db: asyncpg.Connection
) -> None:
    client = make_client()
    visit_id, attempt = await pending_visit(client)
    reply = billing_reply(visit_id, attempt)

    first = await _apply(visits_sessions, reply)
    after_first = await _visit(client, visit_id)
    second = await _apply(visits_sessions, reply)

    assert (first.kind, second.kind) == ("completed", "duplicate")
    assert await _visit(client, visit_id) == after_first
    assert await visits_db.fetchval(
        "SELECT count(*) FROM visits.inbox WHERE event_id = $1", reply.event_id
    ) == 1


# 4.1.5 R3


async def test_second_record_created_on_a_completed_visit_is_a_no_op(
    make_client, visits_sessions
) -> None:
    client = make_client()
    visit_id, attempt = await pending_visit(client)
    await _apply(visits_sessions, billing_reply(visit_id, attempt))
    completed = await _visit(client, visit_id)

    outcome = await _apply(visits_sessions, billing_reply(visit_id, attempt))

    assert outcome.kind == "noop"
    assert await _visit(client, visit_id) == completed


# 4.1.6 T6: a reply for an older attempt is ignored (R1)


@pytest.mark.parametrize("late_type", ["record_created", "failed"])
async def test_t6_reply_with_an_old_attempt_id_is_ignored(
    make_client, visits_sessions, visits_db: asyncpg.Connection, late_type: str
) -> None:
    client = make_client()
    visit_id, attempt_a = await pending_visit(client)
    await _apply(visits_sessions, billing_reply(visit_id, attempt_a, failed=True))
    response = await client.post(f"/api/visits/{visit_id}/complete")
    assert response.status_code == 202, response.text
    attempt_b = response.json()["completion_attempt_id"]
    pending_b = await _visit(client, visit_id)

    late = billing_reply(visit_id, attempt_a, failed=late_type == "failed")
    outcome = await _apply(visits_sessions, late)

    assert outcome.kind == "ignored"
    assert await _visit(client, visit_id) == pending_b
    assert pending_b["completion_attempt_id"] == attempt_b
    assert (await _inbox(visits_db, late.event_id))["processed_at"] is not None  # not again
    assert (await _apply(visits_sessions, late)).kind == "duplicate"

    assert (await _apply(visits_sessions, billing_reply(visit_id, attempt_b))).kind == "completed"
    assert (await _visit(client, visit_id))["status"] == "Completed"


# 4.1.7 BillingFailed for the current attempt (FR8, D16)


@pytest.mark.parametrize("source", ["Scheduled", "In Progress"])
async def test_billing_failed_resets_the_completion_and_allows_a_new_attempt(
    make_client, visits_sessions, source: str
) -> None:
    client = make_client()
    if source == "In Progress":
        visit = await create_visit(client)
        await start_visit(client, visit["id"])
        attempt = (await client.post(f"/api/visits/{visit['id']}/complete")).json()["completion_attempt_id"]
        visit_id = visit["id"]
    else:
        visit_id, attempt = await pending_visit(client)

    outcome = await _apply(visits_sessions, billing_reply(visit_id, attempt, failed=True, reason="no rate"))

    assert outcome.kind == "reset"
    visit = await _visit(client, visit_id)
    assert visit["status"] == source  # back to its source status
    assert visit["completion_pending"] is False
    assert visit["completion_requested_at"] is None
    assert visit["completion_failure_reason"] == "no rate"
    again = await client.post(f"/api/visits/{visit_id}/complete")
    assert again.status_code == 202, again.text
    assert again.json()["completion_attempt_id"] != attempt
    assert again.json()["completion_failure_reason"] is None


async def test_reply_for_an_unknown_visit_raises_unknown_visit(
    visits_sessions, visits_db: asyncpg.Connection
) -> None:
    reply = billing_reply(str(uuid.uuid7()), str(uuid.uuid7()))
    with pytest.raises(UnknownVisit):
        await _apply(visits_sessions, reply)
    assert await _inbox(visits_db, reply.event_id) is None  # rolled back with the transaction


# 4.1.8 Two replies at once for one visit


async def test_two_replies_at_once_are_serialised(make_client, visits_sessions) -> None:
    client = make_client()
    visit_id, attempt = await pending_visit(client)

    outcomes = await asyncio.gather(
        _apply(visits_sessions, billing_reply(visit_id, attempt)),
        _apply(visits_sessions, billing_reply(visit_id, attempt)),
    )

    assert sorted(o.kind for o in outcomes) == ["completed", "noop"]
    assert (await _visit(client, visit_id))["status"] == "Completed"


# BillingFailed for a Completed visit: no-op with a WARNING (approved for M06 IG-7; D23)


async def test_billing_failed_for_a_completed_visit_is_a_no_op_with_a_warning(
    make_client, visits_sessions, caplog: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    visit_id, attempt = await pending_visit(client)
    await _apply(visits_sessions, billing_reply(visit_id, attempt))
    completed = await _visit(client, visit_id)

    with caplog.at_level(logging.WARNING, logger="app.visits"):
        outcome = await _apply(visits_sessions, billing_reply(visit_id, attempt, failed=True))

    assert outcome.kind == "noop"
    assert await _visit(client, visit_id) == completed  # completion_requested_at kept (D23)
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "app.visits.service"
    ]
    assert len(warnings) == 1, warnings
    assert f"visit_id={visit_id}" in warnings[0]
    assert f"completion_attempt_id={attempt}" in warnings[0]
    assert "BillingFailed" in warnings[0]
