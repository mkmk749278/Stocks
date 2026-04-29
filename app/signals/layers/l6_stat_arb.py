from __future__ import annotations

from typing import Any

from app.schemas.tick import TickEvent
from app.signals.base import Layer, LayerSignal


class StatArbLayer(Layer):
    """Layer 6 — Statistical Arbitrage on cointegrated NSE pairs. Stub."""

    name = "STAT_ARB"

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:  # noqa: ARG002
        return None

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:  # noqa: ARG002
        raise NotImplementedError("StatArbLayer.backtest not implemented yet")
