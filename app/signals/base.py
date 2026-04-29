from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.schemas.tick import TickEvent


class Vote(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


@dataclass(slots=True)
class LayerSignal:
    """One layer's verdict at a point in time."""

    layer: str
    vote: Vote
    score: float  # 0.0–100.0; magnitude of conviction
    ts_ist: datetime
    symbol: str
    features: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AggregatedSignal:
    """Output of aggregator when ≥ min_layers agree."""

    symbol: str
    side: Vote
    confidence: float  # weighted 0.0–100.0
    ts_ist: datetime
    layers_voted: int
    breakdown: dict[str, dict[str, Any]]
    regime: str = "UNKNOWN"


class Layer(ABC):
    """Base for all 9 signal layers. Every layer must implement evaluate() and backtest()."""

    name: str = "BASE"

    @abstractmethod
    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:
        """Update internal state with a tick. Return a LayerSignal if conviction crosses threshold."""
        raise NotImplementedError

    @abstractmethod
    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:
        """Run layer over a finite tick sequence; return metrics dict.

        Must include keys: win_rate, profit_factor, sharpe, max_drawdown, n_signals.
        Required by CI (`model-validate.yml`) for any layer that votes.
        """
        raise NotImplementedError
