"""T5: Billing hits a transient error 5 times, with a worker restart between attempts (PRD
section 8; FR7, D15; module-07 task 4.1.9).

Expected: the counter survives the restart; BillingFailed after the fifth attempt. The
transient error is a trigger raising P0001 on the visit's billing record insert.
"""

import json
from pathlib import Path

import asyncpg
import pytest

from tests.integration.helpers import (
    Stack,
    collect_messages,
    create_visit,
    failing_insert_trigger,
    purge_queues,
    start_worker_process,
    stop_worker_process,
    wait_for_consumers,
    wait_for_visit_status,
    wait_until,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_foreign_consumers")]  # DL-32

INBOXES = ("billing.inbox", "visits.inbox")
EXHAUSTION_TIMEOUT_S = 60.0


async def test_t5_counter_survives_a_worker_restart_and_the_fifth_attempt_fails(
    stack: Stack, make_client, billing_db: asyncpg.Connection, tmp_path: Path
) -> None:
    await purge_queues(stack.rabbitmq_url, INBOXES)  # DL-27
    client = make_client()
    visit = await create_visit(client, rate="25.00")
    log_path = tmp_path / "worker.log"

    async def attempts(event_id: str) -> int:
        return await billing_db.fetchval(
            "SELECT coalesce(max(attempts), 0) FROM billing.inbox WHERE event_id = $1::uuid", event_id
        )

    async with failing_insert_trigger(stack, visit["id"]) as trigger:
        first = start_worker_process(stack.env, log_path)
        try:
            assert await wait_for_consumers(stack.rabbitmq_url, INBOXES, 30.0)
            response = await client.post(f"/api/visits/{visit['id']}/complete")
            assert response.status_code == 202, response.text
            attempt = response.json()["completion_attempt_id"]

            async def two_attempts() -> bool:
                return await attempts(attempt) >= 2

            await wait_until(two_attempts, timeout=30.0, message=log_path.read_text())
        finally:
            assert await stop_worker_process(first) == 0, log_path.read_text()
        at_restart = await attempts(attempt)
        assert 2 <= at_restart < 5

        second = start_worker_process(stack.env, log_path)
        try:
            assert await wait_for_consumers(stack.rabbitmq_url, INBOXES, 30.0)

            async def reset() -> bool:
                current = (await client.get(f"/api/visits/{visit['id']}")).json()
                return current["completion_failure_reason"] is not None

            await wait_until(reset, timeout=EXHAUSTION_TIMEOUT_S, message=log_path.read_text())
            inbox = await billing_db.fetchrow(
                "SELECT status, attempts, last_error FROM billing.inbox WHERE event_id = $1::uuid", attempt
            )
            assert (inbox["status"], inbox["attempts"]) == ("failed", 5)  # continued, not restarted at 0
            assert "injected failure" in inbox["last_error"]
            [payload] = [
                json.loads(r["payload"])
                for r in await billing_db.fetch(
                    "SELECT payload FROM billing.outbox WHERE event_type = 'BillingFailed'"
                    " AND payload->>'completion_attempt_id' = $1",
                    attempt,
                )
            ]
            assert payload["error_class"] == "transient_exhausted"
            current = (await client.get(f"/api/visits/{visit['id']}")).json()
            assert (current["status"], current["completion_pending"]) == ("Scheduled", False)
            [parked] = await collect_messages(stack.rabbitmq_url, "billing.parking", {attempt})
            assert parked.message_id == attempt
            assert (await client.get("/api/billing-records", params={"visit_id": visit["id"]})).json() == []

            await trigger.drop()  # the cause is gone
            again = await client.post(f"/api/visits/{visit['id']}/complete")
            assert again.status_code == 202, again.text
            completed = await wait_for_visit_status(client, visit["id"], "Completed")
            assert completed["completion_pending"] is False
            records = (await client.get("/api/billing-records", params={"visit_id": visit["id"]})).json()
            assert [(r["status"], r["amount"]) for r in records] == [("Created", "50.00")]
        finally:
            assert await stop_worker_process(second) == 0, log_path.read_text()
