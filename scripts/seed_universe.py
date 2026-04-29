"""Seed `instruments` with Nifty50 + BankNifty + key F&O underlyings.

Usage (VPS):
    python -m scripts.seed_universe
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db import session_scope
from app.models.instrument import Instrument, Segment

NIFTY50_EQUITY = [
    ("RELIANCE", 738561),
    ("TCS", 2953217),
    ("HDFCBANK", 341249),
    ("ICICIBANK", 1270529),
    ("INFY", 408065),
    ("HINDUNILVR", 356865),
    ("ITC", 424961),
    ("LT", 2939649),
    ("KOTAKBANK", 492033),
    ("AXISBANK", 1510401),
    ("SBIN", 779521),
    ("BHARTIARTL", 2714625),
    ("BAJFINANCE", 81153),
    ("ASIANPAINT", 60417),
    ("MARUTI", 2815745),
    ("HCLTECH", 1850625),
    ("WIPRO", 969473),
    ("TATAMOTORS", 884737),
    ("SUNPHARMA", 857857),
    ("ULTRACEMCO", 2952193),
]

INDEX_FUT = [
    ("NIFTY", 256265),
    ("BANKNIFTY", 260105),
    ("FINNIFTY", 257801),
    ("MIDCPNIFTY", 288009),
]


async def seed() -> None:
    async with await session_scope() as s:
        for sym, tok in NIFTY50_EQUITY:
            existing = (
                await s.execute(select(Instrument).where(Instrument.kite_token == tok))
            ).scalar_one_or_none()
            if existing:
                continue
            s.add(
                Instrument(
                    kite_token=tok,
                    tradingsymbol=sym,
                    exchange="NSE",
                    segment=Segment.EQUITY,
                    lot_size=1,
                    tick_size=0.05,
                )
            )
        for sym, tok in INDEX_FUT:
            existing = (
                await s.execute(select(Instrument).where(Instrument.kite_token == tok))
            ).scalar_one_or_none()
            if existing:
                continue
            s.add(
                Instrument(
                    kite_token=tok,
                    tradingsymbol=sym,
                    exchange="NFO",
                    segment=Segment.FUT_IDX,
                    lot_size=25 if sym == "NIFTY" else 15,
                    tick_size=0.05,
                )
            )
        await s.commit()
    print("seed complete")


if __name__ == "__main__":
    asyncio.run(seed())
