from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.schemas.tick import TickEvent
from app.signals.base import Vote
from app.signals.layers.l1_order_flow import OrderFlowLayer
from app.timeutil import IST


def _make_tick(
    price: float,
    qty: int,
    side: str,
    ts: datetime,
    bid: float | None = None,
    ask: float | None = None,
    bid_qty: int | None = None,
    ask_qty: int | None = None,
) -> TickEvent:
    return TickEvent(
        symbol="RELIANCE",
        kite_token=738561,
        ts_ist=ts,
        price=price,
        qty=qty,
        side=side,
        bid=bid,
        ask=ask,
        bid_qty=bid_qty,
        ask_qty=ask_qty,
    )


@pytest.mark.asyncio
async def test_quiet_market_emits_nothing() -> None:
    layer = OrderFlowLayer()
    base = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    for i in range(60):
        tick = _make_tick(
            price=2500.0 + (i % 2) * 0.05,
            qty=10,
            side="NEUT",
            ts=base + timedelta(seconds=i),
            bid=2499.95,
            ask=2500.05,
            bid_qty=100,
            ask_qty=100,
        )
        assert await layer.on_tick(tick) is None


@pytest.mark.asyncio
async def test_persistent_buy_pressure_emits_buy() -> None:
    layer = OrderFlowLayer()
    base = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    # warm up with NEUT tick history so absorption percentile is computable
    for i in range(60):
        await layer.on_tick(
            _make_tick(2500.0, 5, "NEUT", base + timedelta(seconds=i), 2499.95, 2500.05, 80, 80)
        )
    # now drive: large bullish absorption + ask-stacked book + rising CVD
    sig = None
    for m in range(7):
        bar_start = base + timedelta(minutes=1 + m)
        # 12 BUY-side prints per minute, large size at ask, with little price progression
        for s in range(12):
            ts = bar_start + timedelta(seconds=s * 5)
            tick = _make_tick(
                price=2500.0 + 0.05 * m,
                qty=2000,
                side="BUY",
                ts=ts,
                bid=2499.95 + 0.05 * m,
                ask=2500.0 + 0.05 * m,
                bid_qty=50,
                ask_qty=400,
            )
            out = await layer.on_tick(tick)
            if out is not None:
                sig = out
                break
        if sig is not None:
            break

    assert sig is not None, "expected OrderFlow to emit a BUY under persistent buy pressure"
    assert sig.vote is Vote.BUY
    assert sig.score >= 55.0
    assert sig.layer == "ORDER_FLOW"
    assert "cvd" in sig.features


@pytest.mark.asyncio
async def test_layer_emits_at_most_once_within_cooldown() -> None:
    layer = OrderFlowLayer()
    base = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    # warm history
    for i in range(60):
        await layer.on_tick(
            _make_tick(2500.0, 5, "NEUT", base + timedelta(seconds=i), 2499.95, 2500.05, 80, 80)
        )
    emitted = 0
    # 8 minutes of bullish pressure with slow drift — long enough for CVD slope
    # and VWAP-deviation to activate; cooldown must cap emissions well below the
    # raw tick count.
    total_ticks = 0
    for m in range(8):
        bar_start = base + timedelta(minutes=1 + m)
        for s in range(20):
            total_ticks += 1
            ts = bar_start + timedelta(seconds=s * 3)
            tick = _make_tick(
                price=2500.0 + 0.05 * m,
                qty=2500,
                side="BUY",
                ts=ts,
                bid=2499.95 + 0.05 * m,
                ask=2500.0 + 0.05 * m,
                bid_qty=50,
                ask_qty=600,
            )
            out = await layer.on_tick(tick)
            if out is not None:
                emitted += 1
    assert emitted >= 1, "expected at least one emission under sustained buy pressure"
    assert emitted < total_ticks // 4, "cooldown failed — too many emissions"


def test_backtest_returns_metrics_dict() -> None:
    layer = OrderFlowLayer()
    base = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    ticks: list[TickEvent] = []
    # warm up
    for i in range(60):
        ticks.append(
            _make_tick(2500.0, 5, "NEUT", base + timedelta(seconds=i), 2499.95, 2500.05, 80, 80)
        )
    # bullish phase with subsequent rally
    for m in range(10):
        bar_start = base + timedelta(minutes=1 + m)
        for s in range(15):
            ticks.append(
                _make_tick(
                    2500.0 + m * 0.5,
                    1500,
                    "BUY",
                    bar_start + timedelta(seconds=s * 4),
                    2499.95 + m * 0.5,
                    2500.0 + m * 0.5,
                    50,
                    400,
                )
            )
    metrics = layer.backtest(ticks)
    assert set(metrics.keys()) >= {
        "win_rate",
        "profit_factor",
        "sharpe",
        "max_drawdown",
        "n_signals",
    }
    assert metrics["n_signals"] >= 0
