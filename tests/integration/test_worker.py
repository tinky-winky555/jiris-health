"""Worker process with the two outbox relays (module-04 task 3.1.9; TDD sections 2 and 8.1;
D19, D20). Consumers arrive with M05 and M06, so T1 still expects WorkerNotReady."""

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.integration.helpers import Stack, collect_messages, create_visit

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
STOP_TIMEOUT_S = 10.0


@pytest.fixture
def relay_worker(stack: Stack, tmp_path: Path) -> Iterator[tuple[subprocess.Popen, Path]]:
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


async def test_worker_publishes_a_completion_and_stops_on_sigterm(
    relay_worker: tuple[subprocess.Popen, Path], make_client, stack: Stack
) -> None:
    process, log_path = relay_worker
    client = make_client()
    visit = await create_visit(client)
    response = await client.post(f"/api/visits/{visit['id']}/complete")
    assert response.status_code == 202, response.text
    event_id = response.json()["completion_attempt_id"]

    delivered = await collect_messages(stack.rabbitmq_url, "billing.inbox", {event_id})

    assert [m.message_id for m in delivered] == [event_id], log_path.read_text()
    assert process.poll() is None, log_path.read_text()

    process.send_signal(signal.SIGTERM)
    returncode = await asyncio.to_thread(process.wait, STOP_TIMEOUT_S)
    assert returncode == 0, log_path.read_text()
    log = log_path.read_text()
    assert "relay started schema=visits" in log
    assert "relay started schema=billing" in log
