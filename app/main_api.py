"""API process entry point: exposes create_app() for uvicorn --factory.

The API never talks to RabbitMQ: /complete only writes the outbox (D19). It opens one
pool per module role (D13): visits_app for the Visits routes, billing_app for the
billing records (contract DL-24); it never reads the migration or broker settings.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.billing import api as billing_api
from app.visits import api as visits_api

LOG_HANDLER_NAME = "jiris-app-stderr"

logger = logging.getLogger("app.api")

# Route function name to the command name of the log line (app.visits.api, contract section 3).
COMMANDS = {
    "create_visit": "create",
    "read_visit": "read",
    "complete_visit": "complete",
    "start_visit": "start",
    "cancel_visit": "cancel",
    "mark_missed": "missed",
    "list_billing_records": "list_billing_records",
}


async def _log_rejected(request: Request, error: RequestValidationError) -> JSONResponse:
    """TD-4: a request refused with 422 writes the command line too; the body stays FastAPI's."""
    route = request.scope.get("route")
    name = getattr(route, "name", None)
    visit_id = request.path_params.get("visit_id", "-")
    logger.info(
        "command=%s visit_id=%s event_id=- event_type=- outcome=422 path=%s",
        COMMANDS.get(name, name or "-"),
        visit_id,
        request.url.path,
    )
    return await request_validation_exception_handler(request, error)


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def _configure_logging() -> None:
    """One INFO line per command on stderr (contract section 3, Logging).

    uvicorn configures only its own loggers, so the "app" logger gets its own
    handler; it still propagates, so a root handler also sees the lines.
    """
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    if not any(h.get_name() == LOG_HANDLER_NAME for h in app_logger.handlers):
        handler = logging.StreamHandler()
        handler.set_name(LOG_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        app_logger.addHandler(handler)


def create_app() -> FastAPI:
    visits_url = _required_env("VISITS_DATABASE_URL")
    billing_url = _required_env("BILLING_DATABASE_URL")
    _configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        visits_engine = create_async_engine(visits_url, pool_pre_ping=True)
        billing_engine = create_async_engine(billing_url, pool_pre_ping=True)
        app.state.visits_sessionmaker = async_sessionmaker(visits_engine, expire_on_commit=False)
        app.state.billing_sessionmaker = async_sessionmaker(billing_engine, expire_on_commit=False)
        try:
            yield
        finally:
            await visits_engine.dispose()
            await billing_engine.dispose()

    app = FastAPI(title="Jiris Health", lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, _log_rejected)
    app.include_router(visits_api.router)
    app.include_router(billing_api.router)
    return app
