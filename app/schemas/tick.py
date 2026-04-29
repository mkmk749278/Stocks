from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class TickEvent:
    """Lightweight in-memory tick. DB representation is `app.models.tick.Tick`."""

    symbol: str
    kite_token: int
    ts_ist: datetime
    price: float
    qty: int
    side: str  # "BUY" | "SELL" | "NEUT"
    bid: float | None = None
    ask: float | None = None
    bid_qty: int | None = None
    ask_qty: int | None = None
