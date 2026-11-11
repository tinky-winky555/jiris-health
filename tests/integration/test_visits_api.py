"""Visits HTTP API and the outbox write of /complete (module-03 task 3.1; TDD sections 6.1 to
6.3; FR1 to FR4, FR8, FR10, FR11, R1, R2, R4; contract DL-10 to DL-16).

No worker runs here: events stay in the outbox.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime

import asyncpg
import pytest

from app.contracts import VisitCompleted
from tests.integration.helpers import Stack, create_visit, start_visit

pytestmark = pytest.mark.integration

RACE_RUNS = 50  # module-03 criterion: 3.1.6 passes 50 of 50 runs
LOCK_WAIT_TIMEOUT_S = 10.0
NOT_FOUND = {"detail": "Not Found"}  # DL-10


async def _set_status(visits_db: asyncpg.Connection, visit_id: str, status: str) -> None:
    """Test arrangement: no API path reaches Completed before M06."""
    await visits_db.execute(
        "UPDATE visits.visit SET status = $2 WHERE id = $1::uuid", visit_id, status
    )


async def _outbox_rows(visits_db: asyncpg.Connection, visit_id: str) -> list[asyncpg.Record]:
    return await visits_db.fetch(
        "SELECT * FROM visits.outbox WHERE payload->>'visit_id' = $1 ORDER BY occurred_at",
        visit_id,
    )


async def _unpublished_count(visits_db: asyncpg.Connection, visit_id: str) -> int:
    """Module-03 criterion, for the visit under test (DL-15)."""
    return await visits_db.fetchval(
        "SELECT count(*) FROM visits.outbox"
        " WHERE published_at IS NULL AND payload->>'visit_id' = $1",
        visit_id,
    )


# 3.1.2 Creation and reads


async def test_create_returns_201_with_visit_body(make_client) -> None:
    client = make_client()
    response = await client.post(
        "/api/visits",
        json={
            "start_date_time": "2026-11-11T09:00:00Z",
            "end_date_time": "2026-11-11T11:00:00Z",
            "description": "Evening visit",
            "rate": "25",
        },
    )
    assert response.status_code == 201, response.text
    visit = response.json()
    assert set(visit) == {
        "id",
        "start_date_time",
        "end_date_time",
        "description",
        "rate",
        "status",
        "completion_requested_at",
        "completion_attempt_id",
        "completion_failure_reason",
        "completion_pending",
    }
    uuid.UUID(visit["id"])
    assert visit["status"] == "Scheduled"
    assert visit["rate"] == "25.00"
    assert visit["start_date_time"] == "2026-11-11T09:00:00Z"
    assert visit["description"] == "Evening visit"
    assert visit["completion_pending"] is False
    assert visit["completion_requested_at"] is None
    assert visit["completion_attempt_id"] is None
    assert visit["completion_failure_reason"] is None

    response = await client.get(f"/api/visits/{visit['id']}")
    assert response.status_code == 200
    assert response.json() == visit


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"rate": "0"}, id="rate-zero"),
        pytest.param({"rate": "-5.00"}, id="rate-negative"),
        pytest.param({"rate": "25.001"}, id="rate-three-places"),
        pytest.param({"end_date_time": "2026-11-11T09:00:00Z"}, id="end-equals-start"),
        pytest.param({"end_date_time": "2026-11-11T08:00:00Z"}, id="end-before-start"),
        pytest.param({"start_date_time": "2026-11-11T09:00:00"}, id="naive-start"),
        pytest.param({"status": "Completed"}, id="unknown-field"),
    ],
)
async def test_t8_invalid_creation_returns_422(
    make_client, visits_db: asyncpg.Connection, override: dict
) -> None:
    description = f"Invalid visit {uuid.uuid4()}"
    payload = {
        "start_date_time": "2026-11-11T09:00:00Z",
        "end_date_time": "2026-11-11T11:00:00Z",
        "description": description,
        "rate": "25.00",
    }
    response = await make_client().post("/api/visits", json={**payload, **override})
    assert response.status_code == 422, response.text
    assert await visits_db.fetchval(
        "SELECT count(*) FROM visits.visit WHERE description = $1", description
    ) == 0


async def test_unknown_visit_returns_404_on_every_route(make_client) -> None:
    client = make_client()
    unknown = uuid.uuid7()
    response = await client.get(f"/api/visits/{unknown}")
    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    for action in ("start", "cancel", "missed", "complete"):
        response = await client.post(f"/api/visits/{unknown}/{action}")
        assert (response.status_code, response.json()) == (404, NOT_FOUND), action


async def test_malformed_visit_id_returns_422(make_client) -> None:
    assert (await make_client().get("/api/visits/not-a-uuid")).status_code == 422


# 3.1.4 /complete


@pytest.mark.parametrize("source", ["Scheduled", "In Progress"])
async def test_complete_accepts_and_writes_one_outbox_event(
    make_client, visits_db: asyncpg.Connection, source: str
) -> None:
    client = make_client()
    visit = await create_visit(client, rate="25.00")
    if source == "In Progress":
        await start_visit(client, visit["id"])

    response = await client.post(f"/api/visits/{visit['id']}/complete")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == source  # D18: status unchanged while pending
    assert body["completion_pending"] is True
    assert body["completion_requested_at"] is not None
    attempt_id = body["completion_attempt_id"]

    assert await _unpublished_count(visits_db, visit["id"]) == 1
    [row] = await _outbox_rows(visits_db, visit["id"])
    assert str(row["event_id"]) == attempt_id  # R1: attempt id equals the event id
    assert row["event_type"] == "VisitCompleted"
    assert row["schema_version"] == 1
    assert row["published_at"] is None
    assert row["attempts"] == 0
    assert row["occurred_at"] == datetime.fromisoformat(body["completion_requested_at"])

    payload = json.loads(row["payload"])
    assert VisitCompleted.model_validate(payload).completion_attempt_id == uuid.UUID(attempt_id)
    assert payload == {
        "visit_id": visit["id"],
        "completion_attempt_id": attempt_id,
        "rate": "25.00",
        "start_date_time": "2026-11-11T09:00:00Z",
        "end_date_time": "2026-11-11T11:00:00Z",
    }


async def test_second_complete_while_pending_returns_409(
    make_client, visits_db: asyncpg.Connection
) -> None:
    client = make_client()
    visit = await create_visit(client)
    assert (await client.post(f"/api/visits/{visit['id']}/complete")).status_code == 202

    response = await client.post(f"/api/visits/{visit['id']}/complete")

    assert response.status_code == 409
    assert response.json() == {"reason": "completion_pending"}
    assert len(await _outbox_rows(visits_db, visit["id"])) == 1


@pytest.mark.parametrize("status", ["Completed", "Canceled", "Missed"])
async def test_complete_from_terminal_status_returns_409_invalid_status(
    make_client, visits_db: asyncpg.Connection, status: str
) -> None:
    client = make_client()
    visit = await create_visit(client)
    await _set_status(visits_db, visit["id"], status)

    response = await client.post(f"/api/visits/{visit['id']}/complete")

    assert response.status_code == 409
    assert response.json() == {"reason": "invalid_status"}
    assert await _outbox_rows(visits_db, visit["id"]) == []


# 3.1.6 Concurrency, the first half of T1


@pytest.mark.parametrize("run", range(RACE_RUNS))
async def test_concurrent_complete_has_one_winner_and_one_event(
    run: int, make_client, visits_db: asyncpg.Connection
) -> None:
    visit = await create_visit(make_client())
    await start_visit(make_client(), visit["id"])

    responses = await asyncio.gather(
        make_client().post(f"/api/visits/{visit['id']}/complete"),
        make_client().post(f"/api/visits/{visit['id']}/complete"),
    )

    by_code = sorted(responses, key=lambda r: r.status_code)
    assert [r.status_code for r in by_code] == [202, 409], [r.text for r in by_code]
    assert by_code[1].json() == {"reason": "completion_pending"}
    assert len(await _outbox_rows(visits_db, visit["id"])) == 1


# 3.1.7 Deterministic serialisation on the row lock (DL-16)


async def test_complete_waits_for_the_row_lock_then_loses(
    make_client, stack: Stack, visits_db: asyncpg.Connection
) -> None:
    client = make_client()
    visit = await create_visit(client)
    holder = await asyncpg.connect(stack.visits_dsn)
    try:
        transaction = holder.transaction()
        await transaction.start()
        # The TDD section 6.2 statement, left uncommitted: this connection owns the row.
        updated = await holder.execute(
            """
            UPDATE visits.visit
            SET completion_requested_at = now(),
                completion_attempt_id   = $2,
                completion_failure_reason = NULL
            WHERE id = $1::uuid
              AND status IN ('Scheduled', 'In Progress')
              AND completion_requested_at IS NULL
            """,
            visit["id"],
            uuid.uuid7(),
        )
        assert updated == "UPDATE 1"

        request = asyncio.create_task(client.post(f"/api/visits/{visit['id']}/complete"))
        deadline = time.monotonic() + LOCK_WAIT_TIMEOUT_S
        while not await visits_db.fetchval(
            "SELECT count(*) FROM pg_stat_activity"
            " WHERE wait_event_type = 'Lock' AND query LIKE 'UPDATE visits.visit%'"
        ):
            assert time.monotonic() < deadline, "the request never waited on the row lock"
            assert not request.done(), "the request answered while the row was locked"
            await asyncio.sleep(0.05)
        assert not request.done()

        await transaction.commit()
        response = await asyncio.wait_for(request, LOCK_WAIT_TIMEOUT_S)
    finally:
        await holder.close()

    assert response.status_code == 409
    assert response.json() == {"reason": "completion_pending"}
    assert await _outbox_rows(visits_db, visit["id"]) == []


# 3.1.8 Re-completion after a reset (DL-16; FR8, Visits side)


async def test_complete_after_reset_starts_a_new_attempt(
    make_client, visits_db: asyncpg.Connection
) -> None:
    client = make_client()
    visit = await create_visit(client)
    first = (await client.post(f"/api/visits/{visit['id']}/complete")).json()
    # What M06 does on BillingFailed (TDD section 6.4, step 4).
    await visits_db.execute(
        "UPDATE visits.visit SET completion_requested_at = NULL,"
        " completion_failure_reason = 'permanent: test' WHERE id = $1::uuid",
        visit["id"],
    )
    reset = (await client.get(f"/api/visits/{visit['id']}")).json()
    assert reset["completion_pending"] is False
    assert reset["completion_failure_reason"] == "permanent: test"

    response = await client.post(f"/api/visits/{visit['id']}/complete")

    assert response.status_code == 202, response.text
    second = response.json()
    assert second["completion_failure_reason"] is None
    assert second["completion_pending"] is True
    assert second["completion_attempt_id"] != first["completion_attempt_id"]
    rows = await _outbox_rows(visits_db, visit["id"])
    assert [str(row["event_id"]) for row in rows] == [
        first["completion_attempt_id"],
        second["completion_attempt_id"],
    ]


# 3.1.3 and 3.1.5 Supporting transitions (TDD section 6, D28, R2, DL-11)


async def test_start_moves_scheduled_to_in_progress_once(make_client) -> None:
    client = make_client()
    visit = await create_visit(client)
    started = await start_visit(client, visit["id"])
    assert started["id"] == visit["id"]

    response = await client.post(f"/api/visits/{visit['id']}/start")
    assert response.status_code == 409
    assert response.json() == {"reason": "invalid_status"}


@pytest.mark.parametrize("source", ["Scheduled", "In Progress"])
async def test_cancel_returns_200_with_canceled_visit(make_client, source: str) -> None:
    client = make_client()
    visit = await create_visit(client)
    if source == "In Progress":
        await start_visit(client, visit["id"])

    response = await client.post(f"/api/visits/{visit['id']}/cancel")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "Canceled"


@pytest.mark.parametrize("action", ["start", "cancel", "missed"])
@pytest.mark.parametrize("status", ["Completed", "Canceled", "Missed"])
async def test_transition_from_terminal_status_returns_409_invalid_status(
    make_client, visits_db: asyncpg.Connection, action: str, status: str
) -> None:
    client = make_client()
    visit = await create_visit(client)
    await _set_status(visits_db, visit["id"], status)

    response = await client.post(f"/api/visits/{visit['id']}/{action}")

    assert response.status_code == 409
    assert response.json() == {"reason": "invalid_status"}


async def test_missed_returns_200_from_scheduled_only(make_client) -> None:
    client = make_client()
    scheduled = await create_visit(client)
    response = await client.post(f"/api/visits/{scheduled['id']}/missed")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "Missed"

    in_progress = await create_visit(client)
    await start_visit(client, in_progress["id"])
    response = await client.post(f"/api/visits/{in_progress['id']}/missed")
    assert response.status_code == 409
    assert response.json() == {"reason": "invalid_status"}


@pytest.mark.parametrize("action", ["cancel", "missed", "start"])
async def test_transition_while_pending_returns_409(make_client, action: str) -> None:
    """R2 for cancel and missed; DL-11 for start."""
    client = make_client()
    visit = await create_visit(client)
    assert (await client.post(f"/api/visits/{visit['id']}/complete")).status_code == 202

    response = await client.post(f"/api/visits/{visit['id']}/{action}")

    assert response.status_code == 409
    assert response.json() == {"reason": "completion_pending"}
    current = (await client.get(f"/api/visits/{visit['id']}")).json()
    assert current["status"] == "Scheduled"
    assert current["completion_pending"] is True


# 3.1.9 One log line per command (contract section 3, Logging)


async def test_each_command_writes_one_log_line(
    make_client, caplog: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    visit = await create_visit(client)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.visits"):
        accepted = (await client.post(f"/api/visits/{visit['id']}/complete")).json()
        await client.post(f"/api/visits/{visit['id']}/complete")

    lines = [r.getMessage() for r in caplog.records if r.name == "app.visits.api"]
    assert lines == [
        f"command=complete visit_id={visit['id']} event_id={accepted['completion_attempt_id']}"
        " event_type=VisitCompleted outcome=202",
        f"command=complete visit_id={visit['id']} event_id=- event_type=-"
        " outcome=409 completion_pending",
    ]
