from __future__ import annotations

from typing import Any

from app.schemas.tick import TickEvent
from app.signals.base import Layer, LayerSignal


class InstitutionalLayer(Layer):
    """Layer 4 — Institutional Activity (FII/DII, bulk/block deals, prop desks). Stub."""

    name = "INSTITUTIONAL"

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:  # noqa: ARG002
        return None

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:  # noqa: ARG002
        raise NotImplementedError("InstitutionalLayer.backtest not implemented yet")
