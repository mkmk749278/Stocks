from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable

from app.feed.base import TickFeed
from app.schemas.tick import TickEvent


class ReplayFeed(TickFeed):
    """Deterministic feed for tests and backtests.

    Yields a pre-built sequence of TickEvents. Used by every layer's tests and
    `app.signals.backtest`.
    """

    def __init__(self, ticks: Iterable[TickEvent], delay: float = 0.0) -> None:
        self._ticks = list(ticks)
        self._delay = delay
        self._closed = False

    async def stream(self) -> AsyncIterator[TickEvent]:
        for ev in self._ticks:
            if self._closed:
                return
            if self._delay:
                await asyncio.sleep(self._delay)
            yield ev

    async def close(self) -> None:
        self._closed = True
