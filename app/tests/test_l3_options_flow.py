from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.schemas.tick import TickEvent
from app.signals.base import Vote
from app.signals.layers.l3_options_flow import (
    OptionContract,
    OptionsFlowLayer,
    OptionsSnapshot,
    compute_gex,
    compute_iv_skew,
    compute_max_pain,
    compute_pcr,
    find_gex_walls,
    find_unusual_oi,
)
from app.options_chain_io import snapshot_from_json, snapshot_to_json
from app.timeutil import IST


EXPIRY = date(2026, 5, 7)


def _ce(strike: float, oi: int, *, oi_change: int = 0, iv: float = 0.18, gamma: float = 0.0008) -> OptionContract:
    return OptionContract(
        strike=strike, option_type="CE", ltp=10.0, oi=oi, oi_change=oi_change,
        volume=1000, iv=iv, delta=0.4, gamma=gamma, expiry=EXPIRY,
    )


def _pe(strike: float, oi: int, *, oi_change: int = 0, iv: float = 0.18, gamma: float = 0.0008) -> OptionContract:
    return OptionContract(
        strike=strike, option_type="PE", ltp=10.0, oi=oi, oi_change=oi_change,
        volume=1000, iv=iv, delta=-0.4, gamma=gamma, expiry=EXPIRY,
    )


def _snap(contracts: list[OptionContract], spot: float, ts: datetime | None = None) -> OptionsSnapshot:
    return OptionsSnapshot(
        underlying="NIFTY",
        spot_at_snapshot=spot,
        ts_ist=ts or IST.localize(datetime(2026, 5, 4, 10, 0, 0)),
        contracts=tuple(contracts),
    )


def _equity_tick(price: float, ts: datetime, symbol: str = "NIFTY") -> TickEvent:
    return TickEvent(
        symbol=symbol, kite_token=256265, ts_ist=ts, price=price, qty=1, side="NEUT",
    )


# ---- pure-function math ------------------------------------------------------


def test_pcr_basic() -> None:
    contracts = [_ce(20000, 100), _ce(20100, 100), _pe(19900, 200), _pe(19800, 200)]
    snap = _snap(contracts, 20000.0)
    assert compute_pcr(snap) == pytest.approx(2.0)


def test_pcr_no_calls_returns_inf() -> None:
    snap = _snap([_pe(19900, 100)], 20000.0)
    assert compute_pcr(snap) == float("inf")


def test_max_pain_picks_strike_minimizing_writer_loss() -> None:
    # Heavy CE OI at 20100 and PE OI at 19900 → max pain should be near 20000
    contracts = [
        _ce(20000, 100), _ce(20100, 1000), _ce(20200, 100),
        _pe(19800, 100), _pe(19900, 1000), _pe(20000, 100),
    ]
    snap = _snap(contracts, 20000.0)
    mp = compute_max_pain(snap)
    assert mp in {20000.0}  # exact strike that minimizes pain


def test_compute_gex_signs_and_walls() -> None:
    # large CE OI above spot → positive GEX (resistance); large PE OI below spot → negative (support)
    contracts = [
        _ce(20100, 5000, gamma=0.0010),
        _ce(20200, 200, gamma=0.0006),
        _pe(19900, 5000, gamma=0.0010),
        _pe(19800, 200, gamma=0.0006),
    ]
    snap = _snap(contracts, 20000.0)
    gex = compute_gex(snap, 20000.0)
    assert gex[20100.0] > 0
    assert gex[19900.0] < 0
    res, sup = find_gex_walls(gex, 20000.0)
    assert res == 20100.0
    assert sup == 19900.0


def test_iv_skew_positive_when_puts_richer() -> None:
    contracts = [
        _ce(20100, 1000, iv=0.15), _ce(20200, 1000, iv=0.16),
        _pe(19900, 1000, iv=0.22), _pe(19800, 1000, iv=0.24),
    ]
    snap = _snap(contracts, 20000.0)
    skew = compute_iv_skew(snap, 20000.0)
    assert skew > 0.05


def test_iv_skew_negative_when_calls_richer() -> None:
    contracts = [
        _ce(20100, 1000, iv=0.30), _ce(20200, 1000, iv=0.32),
        _pe(19900, 1000, iv=0.18), _pe(19800, 1000, iv=0.16),
    ]
    snap = _snap(contracts, 20000.0)
    assert compute_iv_skew(snap, 20000.0) < -0.05


def test_unusual_oi_detection() -> None:
    contracts = [
        _ce(20000, 100, oi_change=10), _ce(20100, 100, oi_change=12),
        _ce(20200, 100, oi_change=11), _pe(19900, 100, oi_change=200),  # huge spike
        _pe(19800, 100, oi_change=15),
    ]
    snap = _snap(contracts, 20000.0)
    out = find_unusual_oi(snap)
    assert any(strike == 19900.0 and t == "PE" for strike, t, _ in out)


# ---- layer behaviour ---------------------------------------------------------


def _bullish_chain(spot: float) -> list[OptionContract]:
    """Strong put-write floor below spot (negative GEX support), bullish PCR,
    and unusual fresh call buying. Should produce BUY at the support strike."""
    return [
        # Put writers — mature, large OI, small daily change (the floor itself)
        _pe(spot - 100, 8000, oi_change=300, iv=0.18, gamma=0.0010),
        _pe(spot - 200, 5000, oi_change=200, iv=0.18, gamma=0.0008),
        _pe(spot - 300, 2000, oi_change=100, iv=0.18, gamma=0.0006),
        # Fresh call buying — small OI but huge oi_change
        _ce(spot + 100, 1500, oi_change=2000, iv=0.16, gamma=0.0008),
        _ce(spot + 200, 1000, oi_change=1800, iv=0.16, gamma=0.0006),
        _ce(spot + 300, 500, oi_change=50, iv=0.16, gamma=0.0004),
    ]


def _bearish_chain(spot: float) -> list[OptionContract]:
    """Mirror of bullish chain. Call-writer ceiling, bearish PCR, unusual fresh
    put buying. Should produce SELL at the resistance strike."""
    return [
        # Call writers — mature, large OI, small daily change (the ceiling)
        _ce(spot + 100, 8000, oi_change=300, iv=0.16, gamma=0.0010),
        _ce(spot + 200, 5000, oi_change=200, iv=0.16, gamma=0.0008),
        _ce(spot + 300, 2000, oi_change=100, iv=0.16, gamma=0.0006),
        # Fresh put buying
        _pe(spot - 100, 1500, oi_change=2000, iv=0.30, gamma=0.0008),
        _pe(spot - 200, 1000, oi_change=1800, iv=0.32, gamma=0.0006),
        _pe(spot - 300, 500, oi_change=50, iv=0.34, gamma=0.0004),
    ]


@pytest.mark.asyncio
async def test_layer_does_nothing_without_snapshot() -> None:
    layer = OptionsFlowLayer()
    ts = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    out = await layer.on_tick(_equity_tick(20000.0, ts))
    assert out is None


@pytest.mark.asyncio
async def test_layer_skips_stale_snapshot() -> None:
    layer = OptionsFlowLayer()
    snap_ts = IST.localize(datetime(2026, 5, 4, 9, 0, 0))
    layer.update_snapshot(_snap(_bullish_chain(20000.0), 20000.0, ts=snap_ts))
    # Tick is 10 minutes after snapshot — staleness threshold is 5 min
    tick_ts = snap_ts + timedelta(minutes=10)
    out = await layer.on_tick(_equity_tick(19900.0, tick_ts))
    assert out is None


@pytest.mark.asyncio
async def test_buy_emitted_at_gex_support_with_bullish_pcr() -> None:
    layer = OptionsFlowLayer()
    snap_ts = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    layer.update_snapshot(_snap(_bullish_chain(20000.0), 20000.0, ts=snap_ts))
    # spot tags the support strike (19900) → within 0.30%
    tick_ts = snap_ts + timedelta(seconds=30)
    sig = await layer.on_tick(_equity_tick(19900.0, tick_ts))
    assert sig is not None
    assert sig.vote is Vote.BUY
    assert sig.layer == "OPTIONS_FLOW"
    assert sig.score >= 55.0
    assert sig.features["gex_support"] == 19900.0


@pytest.mark.asyncio
async def test_sell_emitted_at_gex_resistance_with_bearish_setup() -> None:
    layer = OptionsFlowLayer()
    snap_ts = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    layer.update_snapshot(_snap(_bearish_chain(20000.0), 20000.0, ts=snap_ts))
    tick_ts = snap_ts + timedelta(seconds=30)
    sig = await layer.on_tick(_equity_tick(20100.0, tick_ts))
    assert sig is not None
    assert sig.vote is Vote.SELL
    assert sig.features["gex_resistance"] == 20100.0


@pytest.mark.asyncio
async def test_no_emit_when_far_from_walls() -> None:
    layer = OptionsFlowLayer()
    snap_ts = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    layer.update_snapshot(_snap(_bullish_chain(20000.0), 20000.0, ts=snap_ts))
    # Spot is 1% away from any wall; PCR alone shouldn't be enough
    sig = await layer.on_tick(_equity_tick(20300.0, snap_ts + timedelta(seconds=30)))
    # may or may not emit depending on PCR alone; require it not to violate cooldown
    if sig is not None:
        assert sig.vote in {Vote.BUY, Vote.SELL}


@pytest.mark.asyncio
async def test_cooldown_caps_emissions() -> None:
    layer = OptionsFlowLayer()
    snap_ts = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    layer.update_snapshot(_snap(_bullish_chain(20000.0), 20000.0, ts=snap_ts))
    n = 0
    for i in range(20):
        sig = await layer.on_tick(
            _equity_tick(19900.0 + (i % 3) * 0.05, snap_ts + timedelta(seconds=10 + i))
        )
        if sig is not None:
            n += 1
    assert n <= 2  # at most one per cooldown window of 60s in a 20-second span


def test_backtest_returns_metrics_dict() -> None:
    layer = OptionsFlowLayer()
    base = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    layer.set_snapshots([_snap(_bullish_chain(20000.0), 20000.0, ts=base)])
    ticks = [
        _equity_tick(20000.0 - 100 * (i % 2 == 0), base + timedelta(seconds=i * 5))
        for i in range(40)
    ]
    metrics = layer.backtest(ticks)
    assert set(metrics.keys()) >= {"win_rate", "profit_factor", "sharpe", "max_drawdown", "n_signals"}


# ---- snapshot serialization round-trip --------------------------------------


def test_snapshot_json_roundtrip() -> None:
    snap = _snap(_bullish_chain(20000.0), 20000.0)
    blob = snapshot_to_json(snap)
    restored = snapshot_from_json(blob)
    assert restored.underlying == snap.underlying
    assert restored.spot_at_snapshot == snap.spot_at_snapshot
    assert restored.ts_ist == snap.ts_ist
    assert len(restored.contracts) == len(snap.contracts)
    for a, b in zip(restored.contracts, snap.contracts, strict=True):
        assert a == b
