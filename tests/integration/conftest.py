"""Integration fixtures: real PostgreSQL and RabbitMQ in testcontainers (D21).

The stack under test is assembled the same way as in docker-compose:
roles from docker/postgres/init.sql, both Alembic chains under the migration
owner role, the worker as a separate process and the API app in process.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import aio_pika
import asyncpg
import httpx
import pytest
import pytest_asyncio
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import ExecWaitStrategy, LogMessageWaitStrategy

from tests.integration.helpers import (
    RestartableRabbit,
    Stack,
    WorkerNotReady,
    connected_broker,
    consumer_counts,
    purge_queues,
    wait_for_consumers,
)

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = "postgres:18.1-alpine"
RABBITMQ_IMAGE = "rabbitmq:4.2-alpine"
DATABASE = "jiris"
WORKER_READY_TIMEOUT_S = 30.0


def _asyncpg_dsn(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    container = PostgresContainer(
        POSTGRES_IMAGE, username="postgres", password="postgres", dbname=DATABASE, driver=None
    ).waiting_for(ExecWaitStrategy(["pg_isready", "-U", "postgres", "-d", DATABASE]))
    with container:
        yield container


@pytest.fixture(scope="session")
def rabbitmq() -> Iterator[DockerContainer]:
    container = (
        DockerContainer(RABBITMQ_IMAGE)
        .with_exposed_ports(5672)
        .waiting_for(LogMessageWaitStrategy("Server startup complete"))
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def stack(postgres: PostgresContainer, rabbitmq: DockerContainer) -> Stack:
    host = postgres.get_container_host_ip()
    port = postgres.get_exposed_port(5432)

    def url(role: str) -> str:
        return f"postgresql+asyncpg://{role}:{role}@{host}:{port}/{DATABASE}"

    rabbitmq_url = (
        f"amqp://guest:guest@{rabbitmq.get_container_host_ip()}:{rabbitmq.get_exposed_port(5672)}/"
    )
    env = {
        "VISITS_DATABASE_URL": url("visits_app"),
        "BILLING_DATABASE_URL": url("billing_app"),
        "MIGRATIONS_DATABASE_URL": url("jiris_migrator"),
        "RABBITMQ_URL": rabbitmq_url,
    }

    async def bootstrap_roles() -> None:
        conn = await asyncpg.connect(postgres.get_connection_url(driver=None))
        try:
            await conn.execute((ROOT / "docker/postgres/init.sql").read_text())
        finally:
            await conn.close()

    asyncio.run(bootstrap_roles())

    for chain in ("visits", "billing"):
        subprocess.run(
            [sys.executable, "-m", "alembic", "-n", chain, "upgrade", "head"],
            cwd=ROOT,
            env={**os.environ, **env},
            check=True,
        )

    return Stack(
        env=env,
        visits_dsn=_asyncpg_dsn(env["VISITS_DATABASE_URL"]),
        billing_dsn=_asyncpg_dsn(env["BILLING_DATABASE_URL"]),
        rabbitmq_url=rabbitmq_url,
    )




@pytest.fixture(scope="module")
def worker(stack: Stack, tmp_path_factory: pytest.TempPathFactory) -> Iterator[subprocess.Popen]:
    """Run the worker process; ready once both inbox queues have a consumer.

    Module scoped (DL-32): the worker lives only while the module that needs it runs, so it
    never relays or consumes during tests that read queues or assert a pending visit.
    """
    asyncio.run(purge_queues(stack.rabbitmq_url, ("billing.inbox", "visits.inbox")))  # DL-27
    log_path = tmp_path_factory.mktemp("worker") / "worker.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.main_worker"],
            cwd=ROOT,
            env={**os.environ, **stack.env},
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            ready = asyncio.run(
                wait_for_consumers(
                    stack.rabbitmq_url, ("billing.inbox", "visits.inbox"), WORKER_READY_TIMEOUT_S
                )
            )
            if not ready:
                process.terminate()
                raise WorkerNotReady(
                    f"worker not ready (exit code {process.poll()}):\n{log_path.read_text()}"
                )
            yield process
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def api_app(stack: Stack) -> AsyncIterator[object]:
    """The API application in process, configured from the same environment as compose.

    It does not depend on the worker: tests that need the full flow request `worker`.
    """
    os.environ.update(stack.env)
    from app.main_api import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture(loop_scope="session")
async def make_client(api_app: object) -> AsyncIterator:
    """Factory of independent HTTP clients against the in-process API."""
    clients: list[httpx.AsyncClient] = []

    def factory() -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_app), base_url="http://api"
        )
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()


@pytest_asyncio.fixture(loop_scope="session")
async def visits_db(stack: Stack) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(stack.visits_dsn)
    yield conn
    await conn.close()


@pytest_asyncio.fixture(loop_scope="session")
async def billing_db(stack: Stack) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(stack.billing_dsn)
    yield conn
    await conn.close()


# Broker, relay and isolated broker fixtures (M04)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def events_broker(stack: Stack) -> AsyncIterator[object]:
    """The session broker with the topology declared (module-04 task 3.3)."""
    broker = await connected_broker(stack.rabbitmq_url)
    yield broker
    await broker.stop()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def visits_engine(stack: Stack) -> AsyncIterator[object]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(stack.env["VISITS_DATABASE_URL"])
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def billing_engine(stack: Stack) -> AsyncIterator[object]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(stack.env["BILLING_DATABASE_URL"])
    yield engine
    await engine.dispose()


@pytest.fixture
def isolated_rabbitmq() -> Iterator[RestartableRabbit]:
    """A broker of its own, on a fixed host port, for outage and routing failure tests."""
    port = _free_port()
    container = (
        DockerContainer(RABBITMQ_IMAGE)
        .with_bind_ports(5672, port)
        .waiting_for(LogMessageWaitStrategy("Server startup complete"))
    )
    with container:
        yield RestartableRabbit(container, f"amqp://guest:guest@{container.get_container_host_ip()}:{port}/")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def billing_sessions(billing_engine) -> object:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(billing_engine, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def clean_queues(events_broker, stack: Stack) -> AsyncIterator[None]:
    """Purge the session queues after a test that publishes or reads messages (DL-27)."""
    yield
    await purge_queues(stack.rabbitmq_url)


@pytest_asyncio.fixture(loop_scope="session")
async def billing_consumer(events_broker, billing_sessions, stack: Stack) -> AsyncIterator[object]:
    """The Billing subscriber on the session broker for one test."""
    from tests.integration.helpers import start_billing_consumer

    broker = await start_billing_consumer(stack.rabbitmq_url, billing_sessions)
    yield broker
    await broker.stop()


@pytest_asyncio.fixture(loop_scope="session")
async def no_foreign_consumers(stack: Stack) -> None:
    """DL-32: fail loudly when a worker or another consumer is attached to an inbox queue, so a
    test that reads queues or asserts a pending visit never races a live worker."""
    counts = await consumer_counts(stack.rabbitmq_url, ("billing.inbox", "visits.inbox"))
    if any(counts.values()):
        pytest.fail(f"a consumer is attached before the test started: {counts}")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def visits_sessions(visits_engine) -> object:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(visits_engine, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def visits_consumer(events_broker, visits_sessions, stack: Stack) -> AsyncIterator[object]:
    """The Visits subscriber on the session broker for one test."""
    from tests.integration.helpers import start_visits_consumer

    broker = await start_visits_consumer(stack.rabbitmq_url, visits_sessions)
    yield broker
    await broker.stop()
