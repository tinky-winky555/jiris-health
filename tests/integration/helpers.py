"""Shared steps for integration tests."""

import asyncio
import time
from dataclasses import dataclass

import httpx

EVENTUAL_TIMEOUT_S = 10.0  # D28
POLL_INTERVAL_S = 0.1


class WorkerNotReady(Exception):
    """The worker process did not put a consumer on both inbox queues in time.

    T1 expects exactly this error until M06 (contract DL-17); any other error
    in the worker fixture fails the test.
    """


@dataclass(frozen=True)
class Stack:
    """Connection settings of the stack started by the integration fixtures."""

    env: dict[str, str]
    visits_dsn: str
    billing_dsn: str
    rabbitmq_url: str


async def create_visit(
    client: httpx.AsyncClient,
    *,
    start: str = "2026-11-11T09:00:00Z",
    end: str = "2026-11-11T11:00:00Z",
    rate: str = "25.00",
    description: str = "Morning care visit",
) -> dict:
    response = await client.post(
        "/api/visits",
        json={
            "start_date_time": start,
            "end_date_time": end,
            "description": description,
            "rate": rate,
        },
    )
    assert response.status_code == 201, response.text
    visit = response.json()
    assert visit["status"] == "Scheduled"
    return visit


async def start_visit(client: httpx.AsyncClient, visit_id: str) -> dict:
    response = await client.post(f"/api/visits/{visit_id}/start")
    assert response.status_code == 200, response.text
    visit = response.json()
    assert visit["status"] == "In Progress"
    return visit


async def wait_for_visit_status(
    client: httpx.AsyncClient, visit_id: str, status: str, timeout: float = EVENTUAL_TIMEOUT_S
) -> dict:
    """Poll GET /api/visits/{id} until the visit reaches the status (TDD section 11)."""
    deadline = time.monotonic() + timeout
    visit: dict = {}
    while time.monotonic() < deadline:
        response = await client.get(f"/api/visits/{visit_id}")
        assert response.status_code == 200, response.text
        visit = response.json()
        if visit["status"] == status:
            return visit
        await asyncio.sleep(POLL_INTERVAL_S)
    raise AssertionError(f"visit {visit_id} did not reach {status!r} in {timeout} s: {visit}")
