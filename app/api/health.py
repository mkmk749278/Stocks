from __future__ import annotations

from fastapi import APIRouter

from app.timeutil import market_open, now_ist

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, object]:
    ts = now_ist()
    return {
        "status": "ok",
        "ist_now": ts.isoformat(),
        "market_open": market_open(ts),
    }


@router.get("/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready"}
