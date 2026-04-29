from __future__ import annotations

from typing import Any

from app.schemas.tick import TickEvent
from app.signals.base import Layer, LayerSignal


class VolumeProfileLayer(Layer):
    """Layer 2 — Volume Profile (VPOC, VAH, VAL, HVN, LVN). Stubbed for next branch."""

    name = "VOLUME_PROFILE"

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:  # noqa: ARG002
        return None

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:  # noqa: ARG002
        raise NotImplementedError("VolumeProfileLayer.backtest not implemented yet")
