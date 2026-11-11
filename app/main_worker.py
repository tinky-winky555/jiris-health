"""Worker process entry point: two relays, two consumers and the outbox purge job.

Run with: python -m app.main_worker

As of M04 the worker declares the RabbitMQ topology and runs the outbox relays of
both schemas, each with its own role and pool (D13, D19). The consumers arrive with
M05 and M06, the purge job with M08. SIGTERM and SIGINT stop the relays after their
running pass; the process then exits 0.
"""

import asyncio
import logging
import os
import signal

from faststream.rabbit import RabbitBroker
from faststream.rabbit.schemas import Channel
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.outbox.relay import BACKOFF_CEILING_S, POLL_INTERVAL_S, OutboxRelay, backoff_delays
from app.outbox.topology import declare_topology

logger = logging.getLogger("app.worker")

DATABASE_URLS = {"visits": "VISITS_DATABASE_URL", "billing": "BILLING_DATABASE_URL"}


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def _configure_logging() -> None:
    """INFO for the application, WARNING for libraries, one line per record on stderr."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("app").setLevel(logging.INFO)


async def _wait(stop: asyncio.Event, seconds: float) -> bool:
    """Sleep up to `seconds`; True when stop was requested meanwhile."""
    try:
        await asyncio.wait_for(stop.wait(), seconds)
    except TimeoutError:
        return False
    return True


async def _connect(broker: RabbitBroker, stop: asyncio.Event) -> bool:
    """Connect, backing off while the broker is not reachable; False if stopped first."""
    for delay in backoff_delays(POLL_INTERVAL_S, BACKOFF_CEILING_S):
        try:
            await broker.connect()
            return True
        except Exception as error:
            logger.warning("broker connection failed error=%r retry_in=%.1f", error, delay)
        if await _wait(stop, delay):
            return False
    return False


async def run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)

    engines: dict[str, AsyncEngine] = {
        schema: create_async_engine(_required_env(variable), pool_pre_ping=True)
        for schema, variable in DATABASE_URLS.items()
    }
    # Publisher confirms are on by default; a returned mandatory message raises (DL-20).
    broker = RabbitBroker(_required_env("RABBITMQ_URL"), default_channel=Channel(on_return_raises=True))
    try:
        if not await _connect(broker, stop):
            return
        await declare_topology(broker)
        logger.info("topology declared")
        relays = [
            OutboxRelay(schema=schema, engine=engine, broker=broker)
            for schema, engine in engines.items()
        ]
        await asyncio.gather(*(relay.run_forever(stop) for relay in relays))
    finally:
        await broker.stop()
        for engine in engines.values():
            await engine.dispose()
        logger.info("worker stopped")


def main() -> None:
    _configure_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
