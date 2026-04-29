from __future__ import annotations

from datetime import date, datetime

from app.timeutil import (
    IST,
    is_expiry_thursday,
    is_nse_holiday,
    market_open,
)


def _ist(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return IST.localize(datetime(y, m, d, hh, mm))


def test_market_closed_on_weekend() -> None:
    sat = _ist(2026, 5, 2, 11, 0)  # Saturday
    sun = _ist(2026, 5, 3, 11, 0)
    assert market_open(sat) is False
    assert market_open(sun) is False


def test_market_closed_before_open_and_after_close() -> None:
    pre = _ist(2026, 5, 4, 9, 14)   # Mon 09:14 IST
    post = _ist(2026, 5, 4, 15, 31)
    assert market_open(pre) is False
    assert market_open(post) is False


def test_market_open_at_boundaries_on_trading_day() -> None:
    open_edge = _ist(2026, 5, 4, 9, 15)
    close_edge = _ist(2026, 5, 4, 15, 30)
    mid = _ist(2026, 5, 4, 12, 0)
    assert market_open(open_edge) is True
    assert market_open(close_edge) is True
    assert market_open(mid) is True


def test_holiday_recognition() -> None:
    assert is_nse_holiday(date(2026, 1, 26)) is True   # Republic Day
    assert is_nse_holiday(date(2026, 12, 25)) is True  # Christmas
    assert is_nse_holiday(date(2026, 5, 4)) is False   # ordinary Monday


def test_expiry_thursday() -> None:
    assert is_expiry_thursday(date(2026, 5, 7)) is True   # ordinary Thursday
    assert is_expiry_thursday(date(2026, 5, 4)) is False  # Monday
