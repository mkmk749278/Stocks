from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SignalSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class SignalStatus(str, enum.Enum):
    OPEN = "open"
    HIT_T1 = "hit_t1"
    HIT_T2 = "hit_t2"
    HIT_SL = "hit_sl"
    EXPIRED = "expired"


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[SignalSide] = mapped_column(
        Enum(SignalSide, name="signal_side_enum"), nullable=False
    )

    entry_low: Mapped[float] = mapped_column(Float, nullable=False)
    entry_high: Mapped[float] = mapped_column(Float, nullable=False)
    target1: Mapped[float] = mapped_column(Float, nullable=False)
    target2: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    risk_reward: Mapped[float] = mapped_column(Float, nullable=False)

    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, default="5m")
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    regime: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    layers_voted: Mapped[int] = mapped_column(Integer, nullable=False)
    layer_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    status: Mapped[SignalStatus] = mapped_column(
        Enum(SignalStatus, name="signal_status_enum"),
        nullable=False,
        default=SignalStatus.OPEN,
    )

    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
