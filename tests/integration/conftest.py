"""Integration fixtures: real PostgreSQL and RabbitMQ in testcontainers (D21).

The stack under test is assembled the same way as in docker-compose:
roles from docker/postgres/init.sql, both Alembic chains under the migration
owner role, the worker as a separate process and the API app in process.
"""

import asyncio
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import aio_pika
import asyncpg
import httpx
import pytest
import pytest_asyncio
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import ExecWaitStrategy, LogMessageWaitStrategy

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = "postgres:18.1-alpine"
RABBITMQ_IMAGE = "rabbitmq:4.2-alpine"
DATABASE = "jiris"
WORKER_READY_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class Stack:
    env: dict[str, str]
    visits_dsn: str
    billing_dsn: str
    rabbitmq_url: str


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


async def _wait_for_consumers(rabbitmq_url: str, queues: tuple[str, ...], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            connection = await aio_pika.connect(rabbitmq_url)
            async with connection:
                channel = await connection.channel()
                counts = []
                for name in queues:
                    queue = await channel.declare_queue(name, passive=True)
                    counts.append(queue.declaration_result.consumer_count)
                if all(count > 0 for count in counts):
                    return True
        except aio_pika.exceptions.ChannelClosed:
            pass  # queues not declared yet
        await asyncio.sleep(0.2)
    return False


@pytest.fixture(scope="session")
def worker(stack: Stack, tmp_path_factory: pytest.TempPathFactory) -> Iterator[subprocess.Popen]:
    """Run the worker process; ready once both inbox queues have a consumer."""
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
                _wait_for_consumers(
                    stack.rabbitmq_url, ("billing.inbox", "visits.inbox"), WORKER_READY_TIMEOUT_S
                )
            )
            if not ready:
                process.terminate()
                pytest.fail(f"worker not ready (exit code {process.poll()}):\n{log_path.read_text()}")
            yield process
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def api_app(stack: Stack, worker: subprocess.Popen) -> AsyncIterator[object]:
    """The API application in process, configured from the same environment as compose."""
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
