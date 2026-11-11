"""FastAPI router for billing records (TDD section 6.1; contract DL-24).

Reads `billing.billing_record` through the API process's pool as billing_app (D13).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.models import BillingRecord
from app.contracts import Money, Timestamp

router = APIRouter(prefix="/api/billing-records", tags=["billing"])


class BillingRecordOut(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    amount: Money
    status: str
    created_at: Timestamp


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.billing_sessionmaker


Sessions = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]


@router.get("", response_model=list[BillingRecordOut])
async def list_billing_records(visit_id: uuid.UUID, sessions: Sessions) -> list[BillingRecordOut]:
    async with sessions() as session:
        records = (
            await session.execute(
                select(BillingRecord)
                .where(BillingRecord.visit_id == visit_id)
                .order_by(BillingRecord.created_at, BillingRecord.id)
            )
        ).scalars()
        return [
            BillingRecordOut(
                id=r.id, visit_id=r.visit_id, amount=r.amount, status=r.status, created_at=r.created_at
            )
            for r in records
        ]

