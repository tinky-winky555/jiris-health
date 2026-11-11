"""T1: two concurrent /complete requests on one In Progress visit (PRD section 8; NFR2, FR4).

Expected: one 202 and one 409; exactly one VisitCompleted in the Visits outbox;
after processing the visit is Completed with exactly one billing record.
Run 50 times (D28) to give the race a fair chance to show.
"""

import asyncio

import asyncpg
import pytest

from tests.integration.helpers import (
    WorkerNotReady,
    create_visit,
    start_visit,
    wait_for_visit_status,
)

T1_RUNS = 50

pytestmark = pytest.mark.integration


# Contracts DL-6 and DL-17: expected to fail with WorkerNotReady until M06 (Visits
# consumer); any other error fails T1. Remove the marker in M06.
@pytest.mark.xfail(
    strict=True, raises=WorkerNotReady, reason="needs relay and consumers; removed in M06"
)
@pytest.mark.parametrize("run", range(T1_RUNS))
async def test_t1_concurrent_complete_yields_one_winner_and_one_billing_record(
    run: int,
    worker,
    make_client,
    visits_db: asyncpg.Connection,
    billing_db: asyncpg.Connection,
) -> None:
    setup_client = make_client()
    visit = await create_visit(setup_client, rate="25.00")
    visit_id = visit["id"]
    await start_visit(setup_client, visit_id)

    # Two independent clients; each request gets its own database connection.
    first, second = make_client(), make_client()
    responses = await asyncio.gather(
        first.post(f"/api/visits/{visit_id}/complete"),
        second.post(f"/api/visits/{visit_id}/complete"),
    )

    by_code = sorted(responses, key=lambda r: r.status_code)
    assert [r.status_code for r in by_code] == [202, 409], [r.text for r in by_code]
    accepted, rejected = by_code
    assert accepted.json()["completion_pending"] is True
    assert accepted.json()["status"] == "In Progress"  # D18: status unchanged while pending
    assert rejected.json() == {"reason": "completion_pending"}

    outbox_events = await visits_db.fetchval(
        """
        SELECT count(*) FROM visits.outbox
        WHERE event_type = 'VisitCompleted' AND payload->>'visit_id' = $1
        """,
        visit_id,
    )
    assert outbox_events == 1

    completed = await wait_for_visit_status(setup_client, visit_id, "Completed")
    assert completed["completion_pending"] is False

    response = await setup_client.get("/api/billing-records", params={"visit_id": visit_id})
    assert response.status_code == 200, response.text
    records = response.json()
    assert len(records) == 1, records
    assert records[0]["visit_id"] == visit_id
    assert records[0]["status"] == "Created"
    assert records[0]["amount"] == "50.00"  # 25.00 per hour for 2 hours

    stored_records = await billing_db.fetchval(
        "SELECT count(*) FROM billing.billing_record WHERE visit_id = $1::uuid", visit_id
    )
    assert stored_records == 1
