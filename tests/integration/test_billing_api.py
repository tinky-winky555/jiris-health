"""GET /api/billing-records?visit_id= (module-05 task 4.1.10; TDD section 6.1; contract DL-24)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.billing.service import process_visit_completed
from app.contracts import VISIT_COMPLETED, VisitCompleted, new_envelope

pytestmark = pytest.mark.integration


async def _bill(sessions, visit_id: uuid.UUID, rate: str) -> uuid.UUID:
    event_id = uuid.uuid7()
    envelope = new_envelope(
        VISIT_COMPLETED,
        VisitCompleted(
            visit_id=visit_id,
            completion_attempt_id=event_id,
            rate=Decimal(rate),
            start_date_time=datetime(2026, 11, 11, 9, tzinfo=UTC),
            end_date_time=datetime(2026, 11, 11, 10, 30, tzinfo=UTC),
        ),
        event_id=event_id,
    )
    async with sessions.begin() as session:
        return (await process_visit_completed(session, envelope)).billing_record_id


async def test_billing_records_of_a_visit_are_listed(make_client, billing_sessions) -> None:
    visit_id = uuid.uuid7()
    record_id = await _bill(billing_sessions, visit_id, "19.99")

    response = await make_client().get("/api/billing-records", params={"visit_id": str(visit_id)})

    assert response.status_code == 200, response.text
    [record] = response.json()
    assert set(record) == {"id", "visit_id", "amount", "status", "created_at"}
    assert record["id"] == str(record_id)
    assert record["visit_id"] == str(visit_id)
    assert record["amount"] == "29.99"  # 19.99 x 1.5 h = 29.985, half up
    assert record["status"] == "Created"
    assert record["created_at"].endswith("Z")


async def test_a_visit_without_records_gives_an_empty_array(make_client) -> None:
    response = await make_client().get("/api/billing-records", params={"visit_id": str(uuid.uuid7())})
    assert (response.status_code, response.json()) == (200, [])


@pytest.mark.parametrize(
    "params",
    [pytest.param({}, id="missing"), pytest.param({"visit_id": "not-a-uuid"}, id="malformed")],
)
async def test_visit_id_is_required_and_must_be_a_uuid(make_client, params: dict) -> None:
    response = await make_client().get("/api/billing-records", params=params)
    assert response.status_code == 422, response.text
