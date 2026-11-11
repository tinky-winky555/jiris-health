"""T4: Billing hits a permanent error (PRD section 8; FR7, FR8, D15, D16; module-07 task 4.1.8;
contract DL-36).

Expected: BillingFailed; the visit back to its source status with completion_failure_reason;
/complete works again. Reproduced through the API: a rate of 9999999999.99 for 2 hours passes
visit creation and makes the amount overflow numeric(12,2) (SQLSTATE 22003, permanent).
"""

import json
from pathlib import Path

import asyncpg
import pytest

from tests.integration.helpers import (
    Stack,
    assert_no_exception_text,
    create_visit,
    purge_queues,
    start_visit,
    start_worker_process,
    stop_worker_process,
    wait_for_consumers,
    wait_until,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_foreign_consumers")]  # DL-32


async def test_t4_permanent_error_resets_the_visit_and_complete_works_again(
    stack: Stack, make_client, billing_db: asyncpg.Connection, tmp_path: Path
) -> None:
    await purge_queues(stack.rabbitmq_url, ("billing.inbox", "visits.inbox"))  # DL-27
    log_path = tmp_path / "worker.log"
    process = start_worker_process(stack.env, log_path)
    try:
        assert await wait_for_consumers(stack.rabbitmq_url, ("billing.inbox", "visits.inbox"), 30.0)
        client = make_client()
        visit = await create_visit(client, rate="9999999999.99")  # 2 hours: amount overflows
        await start_visit(client, visit["id"])
        response = await client.post(f"/api/visits/{visit['id']}/complete")
        assert response.status_code == 202, response.text
        attempt = response.json()["completion_attempt_id"]

        async def reset() -> bool:
            current = (await client.get(f"/api/visits/{visit['id']}")).json()
            return current["completion_failure_reason"] is not None

        await wait_until(reset, message=f"visit not reset:\n{log_path.read_text()}")
        current = (await client.get(f"/api/visits/{visit['id']}")).json()
        assert current["status"] == "In Progress"  # back to its source status
        assert current["completion_pending"] is False
        assert current["completion_requested_at"] is None
        assert (await client.get("/api/billing-records", params={"visit_id": visit["id"]})).json() == []
        [payload] = [
            json.loads(row["payload"])
            for row in await billing_db.fetch(
                "SELECT payload FROM billing.outbox WHERE event_type = 'BillingFailed'"
                " AND payload->>'completion_attempt_id' = $1",
                attempt,
            )
        ]
        assert payload["error_class"] == "permanent"
        assert payload["reason"] == current["completion_failure_reason"] == "amount_out_of_range"  # TD-7
        raw = await client.get(f"/api/visits/{visit['id']}")
        assert_no_exception_text(raw.text)
        last_error = await billing_db.fetchval(
            "SELECT last_error FROM billing.inbox WHERE event_id = $1::uuid", attempt
        )
        assert "numeric field overflow" in last_error  # the raw text stays in the inbox only

        again = await client.post(f"/api/visits/{visit['id']}/complete")
        assert again.status_code == 202, again.text
        assert again.json()["completion_attempt_id"] != attempt
    finally:
        assert await stop_worker_process(process) == 0, log_path.read_text()
