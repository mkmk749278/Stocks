"""Feeder process: consumes Kite WS ticks and dispatches to Celery.

Run by supervisor (`axiom-feed.conf`):
    python -m app.feed
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.celery_app import celery_app
from app.db import session_scope
from app.feed.kite_ws import KiteWSFeed
from app.logger import configure_logging, get_logger
from app.models.instrument import Instrument
from app.timeutil import market_open

log = get_logger(__name__)


async def _load_universe() -> tuple[list[int], dict[int, str]]:
    async with await session_scope() as s:
        rows = (
            await s.execute(select(Instrument).where(Instrument.is_active.is_(True)))
        ).scalars().all()
    tokens = [int(r.kite_token) for r in rows]
    sym = {int(r.kite_token): r.tradingsymbol for r in rows}
    return tokens, sym


async def main() -> None:
    configure_logging()
    tokens, sym = await _load_universe()
    if not tokens:
        log.error("feeder_no_universe — run scripts/seed_universe.py first")
        return
    feed = KiteWSFeed(tokens, sym)
    await feed.start()
    log.info("feeder_started", tokens=len(tokens))
    try:
        async for tick in feed.stream():
            if not market_open(tick.ts_ist):
                continue
            payload: dict[str, Any] = {
                "symbol": tick.symbol,
                "kite_token": tick.kite_token,
                "ts_ist": tick.ts_ist.isoformat(),
                "price": tick.price,
                "qty": tick.qty,
                "side": tick.side,
                "bid": tick.bid,
                "ask": tick.ask,
                "bid_qty": tick.bid_qty,
                "ask_qty": tick.ask_qty,
            }
            celery_app.send_task("app.tasks.signal_tasks.process_tick", args=[payload])
    finally:
        await feed.close()


if __name__ == "__main__":
    asyncio.run(main())
