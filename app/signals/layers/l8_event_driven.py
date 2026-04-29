from __future__ import annotations

from typing import Any

from app.schemas.tick import TickEvent
from app.signals.base import Layer, LayerSignal


class EventDrivenLayer(Layer):
    """Layer 8 — Event-driven (expiry day, RBI policy, earnings IV crush, Budget). Stub."""

    name = "EVENT_DRIVEN"

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:  # noqa: ARG002
        return None

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:  # noqa: ARG002
        raise NotImplementedError("EventDrivenLayer.backtest not implemented yet")
