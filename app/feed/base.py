from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.schemas.tick import TickEvent


class TickFeed(ABC):
    """Abstract source of NSE/BSE tick events. Every feed yields TickEvents in IST."""

    @abstractmethod
    def stream(self) -> AsyncIterator[TickEvent]:
        """Async iterator of TickEvents."""
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


def infer_side(price: float, bid: float | None, ask: float | None) -> str:
    """Tick-rule classification: trade at/above ask = BUY, at/below bid = SELL, else NEUT."""
    if ask is not None and price >= ask:
        return "BUY"
    if bid is not None and price <= bid:
        return "SELL"
    return "NEUT"
