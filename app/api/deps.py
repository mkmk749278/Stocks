from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.subscription import Plan


async def db_session() -> AsyncIterator[AsyncSession]:
    async for s in get_session():
        yield s


def require_plan(min_plan: Plan):
    """Plan-tier gate. Header `X-Plan` is set by edge auth in production."""

    order = {Plan.FREE: 0, Plan.BASIC: 1, Plan.PREMIUM: 2, Plan.ELITE: 3}

    async def _check(x_plan: str = Header(default=Plan.FREE.value)) -> Plan:
        try:
            plan = Plan(x_plan.lower())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_plan_header"
            ) from exc
        if order[plan] < order[min_plan]:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"plan_{plan.value}_below_required_{min_plan.value}",
            )
        return plan

    return _check
