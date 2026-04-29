from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache

import pytz

from scripts.nse_holidays import NSE_HOLIDAYS_2026

IST = pytz.timezone("Asia/Kolkata")

MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)
SIGNAL_CUTOFF_TIME = time(15, 20)
AUTO_TRADE_OPEN_TIME = time(9, 20)


def now_ist() -> datetime:
    return datetime.now(tz=IST)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return IST.localize(dt)
    return dt.astimezone(IST)


@lru_cache(maxsize=1)
def _holiday_set() -> frozenset[date]:
    return frozenset(NSE_HOLIDAYS_2026)


def is_nse_holiday(d: date) -> bool:
    if d.weekday() >= 5:  # Sat/Sun
        return True
    return d in _holiday_set()


def is_expiry_thursday(d: date) -> bool:
    """Weekly NSE F&O expiry. Rolls back to Wed if Thursday is a holiday."""
    if d.weekday() == 3 and not is_nse_holiday(d):
        return True
    if d.weekday() == 2:
        thursday = d + timedelta(days=1)
        return is_nse_holiday(thursday) and not is_nse_holiday(d)
    return False


def market_open(at: datetime | None = None) -> bool:
    """True if NSE cash equity market is open at the given IST instant."""
    instant = to_ist(at) if at else now_ist()
    if is_nse_holiday(instant.date()):
        return False
    return MARKET_OPEN_TIME <= instant.time() <= MARKET_CLOSE_TIME


def auto_trade_window_open(at: datetime | None = None) -> bool:
    """Tighter window for auto-trade: 9:20 IST – 3:20 IST."""
    instant = to_ist(at) if at else now_ist()
    if is_nse_holiday(instant.date()):
        return False
    return AUTO_TRADE_OPEN_TIME <= instant.time() <= SIGNAL_CUTOFF_TIME
