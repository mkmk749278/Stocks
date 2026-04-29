from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    segment: str
    side: str
    entry_low: float
    entry_high: float
    target1: float
    target2: float | None
    stop_loss: float
    risk_reward: float
    timeframe: str
    confidence: float = Field(ge=0.0, le=100.0)
    regime: str
    layers_voted: int
    layer_breakdown: dict
    status: str
    fired_at: datetime
    closed_at: datetime | None
