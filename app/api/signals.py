from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, require_plan
from app.models.signal import Signal
from app.models.subscription import Plan
from app.schemas.signal import SignalOut
from app.timeutil import now_ist

router = APIRouter(tags=["signals"])


@router.get("/signals", response_model=list[SignalOut])
async def list_signals(
    since: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(db_session),
    plan: Plan = Depends(require_plan(Plan.BASIC)),
) -> list[Signal]:
    cutoff = since or (now_ist() - timedelta(hours=24))
    stmt = (
        select(Signal)
        .where(Signal.fired_at >= cutoff)
        .order_by(desc(Signal.fired_at))
        .limit(limit)
    )
    # Free-plan users get a 15-minute delayed view (handled at edge in production).
    if plan is Plan.FREE:
        stmt = stmt.where(Signal.fired_at <= now_ist() - timedelta(minutes=15))
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)
