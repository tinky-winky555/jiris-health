"""Worker process: topology, the two outbox relays and both consumers (module-04 task 3.1.9,
module-05 task 4.1.12, module-06 task 4.1.14; TDD sections 2, 6.4, 8.1 and 8.2; D19, D20).
The worker consumes both inbox queues, so the test follows the visit, not the queues."""

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

import asyncpg

from tests.integration.helpers import (
    Stack,
    create_visit,
    purge_queues,
    wait_for_visit_status,
    wait_until,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_foreign_consumers")]  # DL-32

ROOT = Path(__file__).resolve().parents[2]
STOP_TIMEOUT_S = 10.0


@pytest.fixture
def relay_worker(stack: Stack, tmp_path: Path) -> Iterator[tuple[subprocess.Popen, Path]]:
    asyncio.run(purge_queues(stack.rabbitmq_url, ("billing.inbox", "visits.inbox")))  # DL-27
    log_path = tmp_path / "worker.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.main_worker"],
            cwd=ROOT,
            env={**os.environ, **stack.env},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            yield process, log_path
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=STOP_TIMEOUT_S)


async def test_worker_bills_a_completion_and_stops_on_sigterm(
    relay_worker: tuple[subprocess.Popen, Path],
    make_client,
    billing_db: asyncpg.Connection,
    stack: Stack,
) -> None:
    process, log_path = relay_worker

    async def topology_declared() -> bool:
        assert process.poll() is None, log_path.read_text()
        return "topology declared" in log_path.read_text()

    # Run alone, the queues exist only once the worker has declared them.
    await wait_until(topology_declared, timeout=30.0, message="worker did not declare the topology")
    client = make_client()
    visit = await create_visit(client)
    response = await client.post(f"/api/visits/{visit['id']}/complete")
    assert response.status_code == 202, response.text
    event_id = response.json()["completion_attempt_id"]

    completed = await wait_for_visit_status(client, visit["id"], "Completed")
    assert completed["completion_pending"] is False
    [record] = (await client.get("/api/billing-records", params={"visit_id": visit["id"]})).json()
    assert (record["status"], record["amount"]) == ("Created", "50.00")
    reply_id = await billing_db.fetchval(
        "SELECT event_id::text FROM billing.outbox WHERE payload->>'completion_attempt_id' = $1",
        event_id,
    )
    assert process.poll() is None, log_path.read_text()

    process.send_signal(signal.SIGTERM)
    returncode = await asyncio.to_thread(process.wait, STOP_TIMEOUT_S)
    assert returncode == 0, log_path.read_text()
    log = log_path.read_text()
    assert "relay started schema=visits" in log
    assert "relay started schema=billing" in log
    assert f"event consumed module=billing event_id={event_id}" in log
    assert f"visit_id={visit['id']}" in log
    assert "outcome=processed" in log
    assert f"event consumed module=visits event_id={reply_id}" in log
    assert "outcome=completed" in log
