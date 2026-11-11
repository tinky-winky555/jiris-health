"""T3: broker stopped, /complete called, broker restarted (PRD section 8; NFR1, NFR4, NFR5;
module-06 task 4.1.13).

Expected: 202; the event waits in the outbox; after the restart the visit is Completed with
one billing record, with no manual step and no restart of the worker.
"""

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import asyncpg
import pytest

from tests.integration.helpers import (
    Stack,
    create_visit,
    wait_for_consumers,
    wait_for_visit_status,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_foreign_consumers")]  # DL-32

ROOT = Path(__file__).resolve().parents[2]
RECOVERY_TIMEOUT_S = 60.0  # relay backoff ceiling 30 s, reconnect interval 5 s, pipeline
STOP_TIMEOUT_S = 10.0


async def test_t3_completion_survives_a_broker_outage(
    isolated_rabbitmq, stack: Stack, make_client, visits_db: asyncpg.Connection, tmp_path: Path
) -> None:
    rabbit = isolated_rabbitmq
    log_path = tmp_path / "worker.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.main_worker"],
            cwd=ROOT,
            env={**os.environ, **stack.env, "RABBITMQ_URL": rabbit.url},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        ready = await wait_for_consumers(rabbit.url, ("billing.inbox", "visits.inbox"), 30.0)
        assert ready, f"worker not ready:\n{log_path.read_text()}"

        rabbit.stop()
        client = make_client()
        visit = await create_visit(client, rate="25.00")
        response = await client.post(f"/api/visits/{visit['id']}/complete")
        assert response.status_code == 202, response.text
        event_id = response.json()["completion_attempt_id"]

        await asyncio.sleep(3.0)
        waiting = (await client.get(f"/api/visits/{visit['id']}")).json()
        assert (waiting["status"], waiting["completion_pending"]) == ("Scheduled", True)
        row = await visits_db.fetchrow(
            "SELECT published_at, attempts FROM visits.outbox WHERE event_id = $1::uuid", event_id
        )
        assert (row["published_at"], row["attempts"]) == (None, 0)  # the event waits

        restarted = time.monotonic()
        rabbit.start()
        await rabbit.wait_ready()
        completed = await wait_for_visit_status(
            client, visit["id"], "Completed", timeout=RECOVERY_TIMEOUT_S
        )
        recovery_s = time.monotonic() - restarted

        assert completed["completion_pending"] is False
        records = (await client.get("/api/billing-records", params={"visit_id": visit["id"]})).json()
        assert [(r["status"], r["amount"]) for r in records] == [("Created", "50.00")]
        assert process.poll() is None, log_path.read_text()  # no worker restart
        print(f"T3 recovery after broker restart: {recovery_s:.1f} s")

        process.send_signal(signal.SIGTERM)
        assert await asyncio.to_thread(process.wait, STOP_TIMEOUT_S) == 0, log_path.read_text()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=STOP_TIMEOUT_S)
