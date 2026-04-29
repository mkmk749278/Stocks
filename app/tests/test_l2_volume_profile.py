from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.schemas.tick import TickEvent
from app.signals.base import Vote
from app.signals.layers.l2_volume_profile import (
    DEFAULT_BUCKET_SIZE,
    VolumeProfileLayer,
    compute_profile,
)
from app.timeutil import IST


def _tick(price: float, qty: int, ts: datetime) -> TickEvent:
    return TickEvent(
        symbol="RELIANCE",
        kite_token=738561,
        ts_ist=ts,
        price=price,
        qty=qty,
        side="NEUT",
    )


# ---- pure-function tests for compute_profile ----------------------------------


def test_compute_profile_vpoc_is_max_volume_bucket() -> None:
    bs = 0.05
    histogram = {
        2000: 1000.0,  # 100.00
        2001: 5000.0,  # 100.05  ← VPOC
        2002: 1500.0,  # 100.10
    }
    snap = compute_profile(histogram, bucket_size=bs, smooth_window=1)
    assert snap is not None
    assert snap.vpoc == pytest.approx(100.05, abs=1e-9)


def test_compute_profile_value_area_contains_70_percent() -> None:
    bs = 0.05
    histogram = {i: float(v) for i, v in zip(range(1000, 1011), [10, 20, 30, 80, 200, 300, 200, 80, 30, 20, 10])}
    snap = compute_profile(histogram, bucket_size=bs)
    assert snap is not None
    total = sum(histogram.values())
    # Sum of buckets within [val_idx, vah_idx] should be >= 70% of total
    val_idx = round(snap.val / bs)
    vah_idx = round(snap.vah / bs)
    in_area = sum(v for i, v in histogram.items() if val_idx <= i <= vah_idx)
    assert in_area >= 0.70 * total


def test_compute_profile_hvn_lvn_extracted() -> None:
    bs = 0.05
    histogram = {i: float(v) for i, v in zip(range(0, 11), [10, 20, 90, 30, 5, 25, 100, 30, 20, 5, 15])}
    snap = compute_profile(histogram, bucket_size=bs, smooth_window=2)
    assert snap is not None
    # bucket index 2 (peak 90) and 6 (peak 100) are HVN; index 4 (5) and 9 (5) are LVN
    assert pytest.approx(2 * bs) in snap.hvn or pytest.approx(6 * bs) in snap.hvn
    assert any(abs(p - 4 * bs) < 1e-9 for p in snap.lvn)


def test_compute_profile_empty() -> None:
    assert compute_profile({}, bucket_size=0.05) is None


# ---- layer behaviour ----------------------------------------------------------


@pytest.mark.asyncio
async def test_no_emission_until_min_volume_reached() -> None:
    layer = VolumeProfileLayer()
    base = IST.localize(datetime(2026, 5, 4, 9, 30, 0))
    # only a few low-volume ticks
    for i in range(10):
        out = await layer.on_tick(_tick(2500.0 + (i % 3) * 0.05, 100, base + timedelta(seconds=i)))
        assert out is None


async def _build_profile_and_settle(layer: VolumeProfileLayer, base: datetime) -> datetime:
    """Build a profile concentrated around 2510 then settle at VPOC long enough
    that the rejection-lookback window contains only neutral history."""
    ts = base
    for _ in range(2000):
        await layer.on_tick(_tick(2510.0, 50, ts))
        ts += timedelta(milliseconds=100)
    for offset, n in [(0.05, 800), (-0.05, 800), (0.10, 300), (-0.10, 300)]:
        for _ in range(n):
            await layer.on_tick(_tick(2510.0 + offset, 30, ts))
            ts += timedelta(milliseconds=100)
    # Settle at VPOC for > 90s so the rejection-lookback window is neutral.
    for _ in range(120):
        await layer.on_tick(_tick(2510.0, 10, ts))
        ts += timedelta(seconds=1)
    return ts


@pytest.mark.asyncio
async def test_buy_signal_at_value_area_low_with_rejection() -> None:
    layer = VolumeProfileLayer()
    base = IST.localize(datetime(2026, 5, 4, 9, 30, 0))
    ts = await _build_profile_and_settle(layer, base)

    # Drive price down to tag VAL, then recover REJECTION_MIN_TICKS above the low.
    sig = None
    for px in [
        2509.95, 2509.95, 2509.95,           # tag VAL (1 tick below)
        2510.00, 2510.05, 2510.10, 2510.15,  # rejection rally
    ]:
        out = await layer.on_tick(_tick(px, 100, ts))
        ts += timedelta(seconds=2)
        if out is not None:
            sig = out
            break

    assert sig is not None, "expected BUY at VAL with rejection"
    assert sig.vote is Vote.BUY
    assert sig.layer == "VOLUME_PROFILE"
    assert sig.score >= 55.0
    assert sig.features["edge"] == "VAL_or_LVN"
    assert "vpoc" in sig.features


@pytest.mark.asyncio
async def test_sell_signal_at_value_area_high_with_rejection() -> None:
    layer = VolumeProfileLayer()
    base = IST.localize(datetime(2026, 5, 4, 9, 30, 0))
    ts = await _build_profile_and_settle(layer, base)

    sig = None
    for px in [
        2510.10, 2510.10, 2510.10,           # tag VAH (1 tick above VAH=2510.05)
        2510.05, 2510.00, 2509.95, 2509.90,  # rejection sell-off
    ]:
        out = await layer.on_tick(_tick(px, 100, ts))
        ts += timedelta(seconds=2)
        if out is not None:
            sig = out
            break

    assert sig is not None, "expected SELL at VAH with rejection"
    assert sig.vote is Vote.SELL
    assert sig.features["edge"] == "VAH_or_HVN"


@pytest.mark.asyncio
async def test_session_reset_clears_profile() -> None:
    layer = VolumeProfileLayer()
    day1 = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    day2 = IST.localize(datetime(2026, 5, 5, 9, 30, 0))

    for _ in range(1500):
        await layer.on_tick(_tick(2500.0, 50, day1))
    state_before = layer._state["RELIANCE"]
    assert state_before.total_volume > 0

    # First tick of next session resets accumulators
    await layer.on_tick(_tick(2600.0, 1, day2))
    state_after = layer._state["RELIANCE"]
    assert state_after.session_date == "2026-05-05"
    assert state_after.total_volume == 1
    assert sum(state_after.histogram.values()) == 1


def test_backtest_returns_metrics_dict() -> None:
    layer = VolumeProfileLayer()
    base = IST.localize(datetime(2026, 5, 4, 9, 30, 0))
    ticks: list[TickEvent] = []
    ts = base
    # build a profile
    for _ in range(1500):
        ticks.append(_tick(2500.0, 50, ts))
        ts += timedelta(milliseconds=200)
    # excursion to VAL with rejection rally
    for px in [2499.95, 2499.90, 2499.85, 2499.90, 2500.00, 2500.10, 2500.20]:
        ticks.append(_tick(px, 100, ts))
        ts += timedelta(seconds=3)
    metrics = layer.backtest(ticks)
    assert set(metrics.keys()) >= {
        "win_rate",
        "profit_factor",
        "sharpe",
        "max_drawdown",
        "n_signals",
    }
    assert metrics["n_signals"] >= 0


def test_default_bucket_matches_constant() -> None:
    assert DEFAULT_BUCKET_SIZE == 0.05  # NSE liquid-equity tick size
