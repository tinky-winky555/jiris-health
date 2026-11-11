"""Outbox purge (R5, D25, NFR7; TDD section 8.1).

Deletes outbox rows published more than 7 days ago, in batches, as the module's own role.
Unpublished rows are never deleted, whatever their age, including rows the relay excluded
(DL-19). Imports neither module; the schema name is checked before it enters SQL.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.outbox.relay import SCHEMAS

logger = logging.getLogger(__name__)

RETENTION = timedelta(days=7)  # D25
BATCH_SIZE = 1000
INTERVAL_S = 3600.0


class OutboxPurge:
    def __init__(
        self,
        *,
        schema: str,
        engine: AsyncEngine,
        retention: timedelta = RETENTION,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        if schema not in SCHEMAS:
            raise ValueError(f"unknown outbox schema: {schema!r}")
        self._schema = schema
        self._engine = engine
        self._retention = retention
        self._batch_size = batch_size
        # One short transaction per batch, so the relay is never blocked for long.
        self._delete = text(
            f"DELETE FROM {schema}.outbox WHERE event_id IN ("
            f" SELECT event_id FROM {schema}.outbox"
            "  WHERE published_at IS NOT NULL AND published_at < now() - CAST(:retention AS interval)"
            "  LIMIT :batch_size FOR UPDATE SKIP LOCKED)"
        )

    async def run_once(self) -> int:
        """Delete every expired published row; returns the number of rows deleted."""
        deleted = 0
        while True:
            async with self._engine.begin() as conn:
                result = await conn.execute(
                    self._delete, {"retention": self._retention, "batch_size": self._batch_size}
                )
            deleted += result.rowcount
            if result.rowcount < self._batch_size:
                break
        logger.info("outbox purged schema=%s deleted=%d", self._schema, deleted)
        return deleted

    async def run_forever(self, stop: asyncio.Event, interval: float = INTERVAL_S) -> None:
        """A pass at start, then one every `interval` seconds, until `stop` is set."""
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception as error:  # a failed pass is retried at the next interval
                logger.warning("outbox purge failed schema=%s error=%r", self._schema, error)
            try:
                await asyncio.wait_for(stop.wait(), interval)
            except TimeoutError:
                pass
