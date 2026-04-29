from __future__ import annotations

from typing import Any

from app.schemas.tick import TickEvent
from app.signals.base import Layer, LayerSignal


class NLPSentimentLayer(Layer):
    """Layer 7 — NLP Sentiment (FinBERT on MoneyControl, ET Markets, NSE). Stub."""

    name = "NLP_SENTIMENT"

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:  # noqa: ARG002
        return None

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:  # noqa: ARG002
        raise NotImplementedError("NLPSentimentLayer.backtest not implemented yet")
