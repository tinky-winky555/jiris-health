"""FastAPI router for the Visits HTTP API (TDD sections 6.1 and 6.3).

Each endpoint owns its transaction explicitly, so the response is built only
after COMMIT: a 202 always means the outbox row is durable. Each command writes
one log line after COMMIT or rollback (contract section 3, Logging).
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Annotated, Self

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts import VISIT_COMPLETED, Money, Timestamp
from app.visits import service
from app.visits.models import Visit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/visits", tags=["visits"])


class VisitCreate(BaseModel):
    """Creation payload; invalid input gives 422 (FR11, D24, contract DL-12 and DL-13)."""

    model_config = ConfigDict(extra="forbid")

    start_date_time: AwareDatetime
    end_date_time: AwareDatetime
    description: str
    rate: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end_date_time <= self.start_date_time:
            raise ValueError("end_date_time must be after start_date_time")
        return self


class VisitOut(BaseModel):
    """Visit body: the columns of TDD section 5.1 plus the derived completion_pending."""

    id: uuid.UUID
    start_date_time: Timestamp
    end_date_time: Timestamp
    description: str
    rate: Money
    status: str
    completion_requested_at: Timestamp | None
    completion_attempt_id: uuid.UUID | None
    completion_failure_reason: str | None
    completion_pending: bool

    @classmethod
    def of(cls, visit: Visit) -> Self:
        return cls(
            id=visit.id,
            start_date_time=visit.start_date_time,
            end_date_time=visit.end_date_time,
            description=visit.description,
            rate=visit.rate,
            status=visit.status,
            completion_requested_at=visit.completion_requested_at,
            completion_attempt_id=visit.completion_attempt_id,
            completion_failure_reason=visit.completion_failure_reason,
            completion_pending=service.is_completion_pending(visit),
        )


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.visits_sessionmaker


Sessions = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]
Operation = Callable[[AsyncSession, uuid.UUID], Awaitable[Visit]]


def _log(
    command: str,
    visit_id: uuid.UUID,
    outcome: str,
    event_id: uuid.UUID | None = None,
    event_type: str | None = None,
) -> None:
    logger.info(
        "command=%s visit_id=%s event_id=%s event_type=%s outcome=%s",
        command,
        visit_id,
        event_id or "-",
        event_type or "-",
        outcome,
    )


async def _run(
    command: str, sessions: Sessions, visit_id: uuid.UUID, operation: Operation, code: int
) -> JSONResponse:
    try:
        async with sessions.begin() as session:
            body = VisitOut.of(await operation(session, visit_id))
    except service.VisitNotFound:
        _log(command, visit_id, str(status.HTTP_404_NOT_FOUND))
        raise HTTPException(status.HTTP_404_NOT_FOUND) from None  # body per DL-10
    except service.VisitConflict as conflict:
        _log(command, visit_id, f"{status.HTTP_409_CONFLICT} {conflict.reason}")
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"reason": conflict.reason})
    if command == "complete":
        _log(command, visit_id, str(code), body.completion_attempt_id, VISIT_COMPLETED.event_type)
    else:
        _log(command, visit_id, str(code))
    return JSONResponse(status_code=code, content=body.model_dump(mode="json"))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=VisitOut)
async def create_visit(data: VisitCreate, sessions: Sessions) -> VisitOut:
    async with sessions.begin() as session:
        visit = await service.create_visit(session, service.NewVisit(**data.model_dump()))
        body = VisitOut.of(visit)
    _log("create", body.id, str(status.HTTP_201_CREATED))
    return body


@router.get("/{visit_id}", response_model=VisitOut)
async def read_visit(visit_id: uuid.UUID, sessions: Sessions) -> JSONResponse:
    return await _run("read", sessions, visit_id, service.get_visit, status.HTTP_200_OK)


@router.post("/{visit_id}/complete", response_model=VisitOut, status_code=status.HTTP_202_ACCEPTED)
async def complete_visit(visit_id: uuid.UUID, sessions: Sessions) -> JSONResponse:
    return await _run(
        "complete", sessions, visit_id, service.request_completion, status.HTTP_202_ACCEPTED
    )


@router.post("/{visit_id}/start", response_model=VisitOut)
async def start_visit(visit_id: uuid.UUID, sessions: Sessions) -> JSONResponse:
    return await _run("start", sessions, visit_id, service.start_visit, status.HTTP_200_OK)


@router.post("/{visit_id}/cancel", response_model=VisitOut)
async def cancel_visit(visit_id: uuid.UUID, sessions: Sessions) -> JSONResponse:
    return await _run("cancel", sessions, visit_id, service.cancel_visit, status.HTTP_200_OK)


@router.post("/{visit_id}/missed", response_model=VisitOut)
async def mark_missed(visit_id: uuid.UUID, sessions: Sessions) -> JSONResponse:
    return await _run("missed", sessions, visit_id, service.mark_missed, status.HTTP_200_OK)
