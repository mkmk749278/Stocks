from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Segment(str, enum.Enum):
    EQUITY = "equity"
    FUT_IDX = "fut_idx"
    OPT_IDX = "opt_idx"
    FUT_STK = "fut_stk"
    OPT_STK = "opt_stk"
    CURRENCY = "currency"
    COMMODITY = "commodity"


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kite_token: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    tradingsymbol: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    exchange: Mapped[str] = mapped_column(String(8), nullable=False)  # NSE | BSE | NFO | MCX | CDS
    segment: Mapped[Segment] = mapped_column(
        Enum(Segment, name="segment_enum"), nullable=False
    )
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tick_size: Mapped[float] = mapped_column(nullable=False, default=0.05)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
