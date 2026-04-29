from __future__ import annotations

from typing import Any

from app.schemas.tick import TickEvent
from app.signals.base import Layer, LayerSignal


class MLModelsLayer(Layer):
    """Layer 5 — ML Models (LSTM intraday, XGBoost quality, HMM regime). Stub."""

    name = "ML_MODELS"

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:  # noqa: ARG002
        return None

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:  # noqa: ARG002
        raise NotImplementedError("MLModelsLayer.backtest not implemented yet")
