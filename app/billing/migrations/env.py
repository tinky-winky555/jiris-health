"""Alembic environment for schema "billing" (D26), run under the migration owner role (D29)."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.billing.models import SCHEMA, Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get("MIGRATIONS_DATABASE_URL")
    if not url:
        raise RuntimeError("MIGRATIONS_DATABASE_URL is not set")
    return url


def _include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    if type_ == "schema":
        return name == SCHEMA
    return True


def _run_migrations(connection: Connection) -> None:
    # The version table lives in the module schema, so the schema must exist first.
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    connection.commit()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=_include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline migrations are not supported; run against a database")

asyncio.run(_run_online())
