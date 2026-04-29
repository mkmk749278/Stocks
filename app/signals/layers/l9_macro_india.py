from __future__ import annotations

from typing import Any

from app.schemas.tick import TickEvent
from app.signals.base import Layer, LayerSignal


class MacroIndiaLayer(Layer):
    """Layer 9 — Macro India (GIFT Nifty, India VIX, DXY, crude, US pre-mkt). Stub."""

    name = "MACRO_INDIA"

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:  # noqa: ARG002
        return None

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:  # noqa: ARG002
        raise NotImplementedError("MacroIndiaLayer.backtest not implemented yet")
