"""R7 (PRD NFR5; module-08 task 3.1.3): relays and consumers reconnect to the broker
automatically with backoff, beyond the restart that T3 covers: a broker that is down when the
worker starts, and connections closed by the broker while the worker runs."""

import asyncio
from pathlib import Path

import pytest

from tests.integration.helpers import (
    Stack,
    create_visit,
    start_worker_process,
    stop_worker_process,
    wait_for_consumers,
    wait_for_visit_status,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_foreign_consumers")]  # DL-32

INBOXES = ("billing.inbox", "visits.inbox")


async def _completes(make_client) -> None:
    client = make_client()
    visit = await create_visit(client)
    response = await client.post(f"/api/visits/{visit['id']}/complete")
    assert response.status_code == 202, response.text
    await wait_for_visit_status(client, visit["id"], "Completed", timeout=30.0)


async def test_worker_started_while_the_broker_is_down_connects_when_it_returns(
    isolated_rabbitmq, stack: Stack, make_client, tmp_path: Path
) -> None:
    rabbit = isolated_rabbitmq
    log_path = tmp_path / "worker.log"
    rabbit.stop()
    process = start_worker_process({**stack.env, "RABBITMQ_URL": rabbit.url}, log_path)
    try:
        await asyncio.sleep(3.0)
        assert process.poll() is None, log_path.read_text()
        assert "broker connection failed" in log_path.read_text()

        rabbit.start()
        await rabbit.wait_ready()
        assert await wait_for_consumers(rabbit.url, INBOXES, 60.0), log_path.read_text()
        await _completes(make_client)
        assert process.poll() is None
    finally:
        assert await stop_worker_process(process) == 0, log_path.read_text()


async def test_worker_recovers_after_the_broker_closes_its_connections(
    isolated_rabbitmq, stack: Stack, make_client, tmp_path: Path
) -> None:
    rabbit = isolated_rabbitmq
    log_path = tmp_path / "worker.log"
    process = start_worker_process({**stack.env, "RABBITMQ_URL": rabbit.url}, log_path)
    try:
        assert await wait_for_consumers(rabbit.url, INBOXES, 30.0), log_path.read_text()
        result = rabbit.container.get_wrapped_container().exec_run(
            ["rabbitmqctl", "close_all_connections", "R7 test"]
        )
        assert result.exit_code == 0, result.output
        await asyncio.sleep(1.0)  # let the broker drop the consumers before counting them again

        assert await wait_for_consumers(rabbit.url, INBOXES, 60.0), log_path.read_text()
        await _completes(make_client)
        assert process.poll() is None, log_path.read_text()  # recovered in place, never restarted
    finally:
        assert await stop_worker_process(process) == 0, log_path.read_text()
