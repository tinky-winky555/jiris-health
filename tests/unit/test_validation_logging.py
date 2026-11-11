"""TD-4 (module-08 task 3.1.6): a request rejected with 422 writes one command log line and keeps
FastAPI's validation body."""

import logging

import httpx
import pytest

from app.main_api import create_app

VISITS_URL = "postgresql+asyncpg://visits_app:x@localhost/jiris"
BILLING_URL = "postgresql+asyncpg://billing_app:x@localhost/jiris"


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VISITS_DATABASE_URL", VISITS_URL)
    monkeypatch.setenv("BILLING_DATABASE_URL", BILLING_URL)
    app = create_app()
    async with app.router.lifespan_context(app):  # engines are lazy: no connection is opened
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as c:
            yield c


def _lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("command=")]


async def test_rejected_creation_is_logged_and_keeps_the_body(client, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app"):
        response = await client.post("/api/visits", json={"rate": "0"})
    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list) and body["detail"][0]["type"]
    [line] = _lines(caplog)
    assert "outcome=422" in line
    assert "path=/api/visits" in line
    assert "command=create" in line


async def test_rejected_billing_query_is_logged(client, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app"):
        response = await client.get("/api/billing-records")
    assert response.status_code == 422
    [line] = _lines(caplog)
    assert "outcome=422" in line and "path=/api/billing-records" in line
