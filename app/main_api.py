"""API process entry point: exposes create_app() for uvicorn --factory.

The API never talks to RabbitMQ: /complete only writes the outbox (D19). It
connects to PostgreSQL as visits_app only (D13); no other URL is read.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.visits import api as visits_api


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def create_app() -> FastAPI:
    visits_url = _required_env("VISITS_DATABASE_URL")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        visits_engine = create_async_engine(visits_url, pool_pre_ping=True)
        app.state.visits_sessionmaker = async_sessionmaker(visits_engine, expire_on_commit=False)
        try:
            yield
        finally:
            await visits_engine.dispose()

    app = FastAPI(title="Jiris Health", lifespan=lifespan)
    app.include_router(visits_api.router)
    return app
