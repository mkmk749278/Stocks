from __future__ import annotations

from typing import Any

from app.schemas.tick import TickEvent
from app.signals.base import Layer, LayerSignal


class OptionsFlowLayer(Layer):
    """Layer 3 — Options Flow (GEX, unusual OI, IV skew, PCR, Max Pain). Stub."""

    name = "OPTIONS_FLOW"

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:  # noqa: ARG002
        return None

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:  # noqa: ARG002
        raise NotImplementedError("OptionsFlowLayer.backtest not implemented yet")
