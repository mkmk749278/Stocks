from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Tick(Base):
    """Hot table — partition by day in ops; keep schema minimal."""

    __tablename__ = "ticks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kite_token: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    ts_ist: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY | SELL | NEUT
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ask_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
