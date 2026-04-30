from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.institutional_io import snapshot_from_json, snapshot_to_json
from app.schemas.tick import TickEvent
from app.signals.base import Vote
from app.signals.layers.l4_institutional import (
    BlockDeal,
    BulkDeal,
    FlowDay,
    InstitutionalLayer,
    InstitutionalSnapshot,
    aggregate_block_deals,
    aggregate_bulk_deals,
    classify_block_deal,
    compute_flow_bias,
    is_known_institution,
)
from app.timeutil import IST


TODAY = date(2026, 5, 4)


def _flow(d: date, fii_net: float, dii_net: float = 0.0) -> FlowDay:
    return FlowDay(
        trade_date=d,
        fii_buy=max(0.0, fii_net),
        fii_sell=max(0.0, -fii_net),
        dii_buy=max(0.0, dii_net),
        dii_sell=max(0.0, -dii_net),
    )


def _bulk(symbol: str, client: str, side: str, qty: int) -> BulkDeal:
    return BulkDeal(
        trade_date=TODAY, symbol=symbol, client_name=client,
        side=side, quantity=qty, avg_price=2500.0,
    )


def _block(symbol: str, side: str, qty: int, price: float) -> BlockDeal:
    return BlockDeal(
        trade_date=TODAY, symbol=symbol, side=side,
        quantity=qty, trade_price=price,
    )


def _tick(price: float, ts: datetime, symbol: str = "RELIANCE") -> TickEvent:
    return TickEvent(
        symbol=symbol, kite_token=738561, ts_ist=ts, price=price, qty=100, side="NEUT",
    )


# ---- pure-function math ------------------------------------------------------


def test_flow_bias_zero_when_constant() -> None:
    flows = [_flow(TODAY - timedelta(days=i), 100.0) for i in range(5)]
    z, last = compute_flow_bias(flows)
    assert z == 0.0
    assert last == 100.0


def test_flow_bias_positive_on_fresh_buying_spike() -> None:
    base = [_flow(TODAY - timedelta(days=i), -200.0) for i in range(1, 5)]
    spike = _flow(TODAY, 800.0)
    z, last = compute_flow_bias(base + [spike])
    assert z > 1.0
    assert last == 800.0


def test_flow_bias_negative_on_fresh_selling_spike() -> None:
    base = [_flow(TODAY - timedelta(days=i), 100.0) for i in range(1, 5)]
    spike = _flow(TODAY, -1500.0)
    z, _ = compute_flow_bias(base + [spike])
    assert z < -1.0


def test_flow_bias_empty_returns_zero() -> None:
    z, last = compute_flow_bias([])
    assert z == 0.0
    assert last == 0.0


def test_is_known_institution() -> None:
    assert is_known_institution("HDFC MUTUAL FUND") is True
    assert is_known_institution("ICICI PRUDENTIAL ASSET MANAGEMENT") is True
    assert is_known_institution("Goldman Sachs (Singapore) Pte") is True
    assert is_known_institution("Random Retail Trader 12345") is False


def test_aggregate_bulk_deals_filters_non_institutional() -> None:
    deals = [
        _bulk("RELIANCE", "HDFC MUTUAL FUND", "BUY", 1_00_000),
        _bulk("RELIANCE", "Random Retail", "BUY", 1_000_000),  # ignored
        _bulk("RELIANCE", "ICICI Prudential AMC", "SELL", 30_000),
        _bulk("INFY", "HDFC Mutual Fund", "BUY", 5_00_000),    # different symbol
    ]
    out = aggregate_bulk_deals(deals, "RELIANCE")
    assert out["inst_buy"] == 1_00_000
    assert out["inst_sell"] == 30_000
    assert out["net_qty"] == 70_000
    assert out["n_deals"] == 2


def test_classify_block_deal_premium_discount_neutral() -> None:
    bd_premium = _block("RELIANCE", "BUY", 1_000, 2515.0)   # +0.6%
    bd_discount = _block("RELIANCE", "SELL", 1_000, 2485.0)  # -0.6%
    bd_neutral = _block("RELIANCE", "BUY", 1_000, 2502.0)    # +0.08%
    assert classify_block_deal(bd_premium, 2500.0) == "premium"
    assert classify_block_deal(bd_discount, 2500.0) == "discount"
    assert classify_block_deal(bd_neutral, 2500.0) == "neutral"


def test_aggregate_block_deals_counts() -> None:
    deals = [
        _block("RELIANCE", "BUY", 1_000, 2520.0),   # premium
        _block("RELIANCE", "BUY", 1_000, 2515.0),   # premium
        _block("RELIANCE", "SELL", 1_000, 2480.0),  # discount
        _block("INFY", "BUY", 1_000, 1500.0),       # different symbol
    ]
    agg = aggregate_block_deals(deals, "RELIANCE", ref_price=2500.0)
    assert agg["premium"] == 2
    assert agg["discount"] == 1
    assert agg["n_deals"] == 3


# ---- layer behaviour ---------------------------------------------------------


def _bullish_snapshot() -> InstitutionalSnapshot:
    flows = [
        _flow(TODAY - timedelta(days=4), -100.0),
        _flow(TODAY - timedelta(days=3), -200.0),
        _flow(TODAY - timedelta(days=2), -150.0),
        _flow(TODAY - timedelta(days=1), 50.0),
        _flow(TODAY, 1200.0),  # huge net buy
    ]
    bulk = [
        _bulk("RELIANCE", "HDFC Mutual Fund", "BUY", 5_00_000),
        _bulk("RELIANCE", "ICICI Prudential AMC", "BUY", 3_00_000),
    ]
    block = [
        _block("RELIANCE", "BUY", 50_000, 2520.0),  # premium relative to ~2500
        _block("RELIANCE", "BUY", 30_000, 2518.0),  # premium
    ]
    return InstitutionalSnapshot(
        as_of=TODAY,
        flows=tuple(flows),
        bulk_deals=tuple(bulk),
        block_deals=tuple(block),
    )


def _bearish_snapshot() -> InstitutionalSnapshot:
    flows = [
        _flow(TODAY - timedelta(days=4), 100.0),
        _flow(TODAY - timedelta(days=3), 200.0),
        _flow(TODAY - timedelta(days=2), 150.0),
        _flow(TODAY - timedelta(days=1), 0.0),
        _flow(TODAY, -1500.0),
    ]
    bulk = [
        _bulk("RELIANCE", "HDFC Mutual Fund", "SELL", 4_00_000),
        _bulk("RELIANCE", "Goldman Sachs FPI", "SELL", 6_00_000),
    ]
    block = [
        _block("RELIANCE", "SELL", 40_000, 2480.0),  # discount
        _block("RELIANCE", "SELL", 30_000, 2475.0),  # discount
    ]
    return InstitutionalSnapshot(
        as_of=TODAY,
        flows=tuple(flows),
        bulk_deals=tuple(bulk),
        block_deals=tuple(block),
    )


@pytest.mark.asyncio
async def test_layer_does_nothing_without_snapshot() -> None:
    layer = InstitutionalLayer()
    ts = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    assert await layer.on_tick(_tick(2500.0, ts)) is None


@pytest.mark.asyncio
async def test_layer_skips_stale_snapshot() -> None:
    layer = InstitutionalLayer()
    snap = _bullish_snapshot()
    # tweak as_of to be 5 days old
    layer.update_snapshot(
        InstitutionalSnapshot(
            as_of=TODAY - timedelta(days=5),
            flows=snap.flows,
            bulk_deals=snap.bulk_deals,
            block_deals=snap.block_deals,
        )
    )
    ts = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    assert await layer.on_tick(_tick(2500.0, ts)) is None


@pytest.mark.asyncio
async def test_buy_emitted_on_bullish_institutional_setup() -> None:
    layer = InstitutionalLayer()
    layer.update_snapshot(_bullish_snapshot())
    ts = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    sig = await layer.on_tick(_tick(2500.0, ts))
    assert sig is not None
    assert sig.vote is Vote.BUY
    assert sig.layer == "INSTITUTIONAL"
    assert sig.score >= 55.0
    assert sig.features["bulk_net_qty"] > 0
    assert sig.features["block_premium"] >= 1


@pytest.mark.asyncio
async def test_sell_emitted_on_bearish_institutional_setup() -> None:
    layer = InstitutionalLayer()
    layer.update_snapshot(_bearish_snapshot())
    ts = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    sig = await layer.on_tick(_tick(2500.0, ts))
    assert sig is not None
    assert sig.vote is Vote.SELL
    assert sig.features["bulk_net_qty"] < 0
    assert sig.features["block_discount"] >= 1


@pytest.mark.asyncio
async def test_no_vote_when_no_corroboration_for_symbol() -> None:
    """Strong index-wide flow but no symbol-specific deals → not enough to fire."""
    layer = InstitutionalLayer()
    flows = [
        _flow(TODAY - timedelta(days=4), -100.0),
        _flow(TODAY - timedelta(days=3), -200.0),
        _flow(TODAY - timedelta(days=2), -150.0),
        _flow(TODAY - timedelta(days=1), 50.0),
        _flow(TODAY, 1200.0),
    ]
    layer.update_snapshot(
        InstitutionalSnapshot(
            as_of=TODAY, flows=tuple(flows), bulk_deals=(), block_deals=(),
        )
    )
    ts = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    assert await layer.on_tick(_tick(2500.0, ts, symbol="UNTRACKED")) is None


@pytest.mark.asyncio
async def test_cooldown_prevents_repeated_emissions() -> None:
    layer = InstitutionalLayer()
    layer.update_snapshot(_bullish_snapshot())
    base = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    n = 0
    for i in range(20):
        sig = await layer.on_tick(_tick(2500.0, base + timedelta(seconds=i * 30)))
        if sig is not None:
            n += 1
    # 5-min cooldown over a 10-min span → expect 2-3 emissions max
    assert 1 <= n <= 3


def test_backtest_returns_metrics_dict() -> None:
    layer = InstitutionalLayer()
    layer.update_snapshot(_bullish_snapshot())
    base = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    ticks = [
        _tick(2500.0 + i * 0.05, base + timedelta(minutes=i * 5))
        for i in range(40)
    ]
    metrics = layer.backtest(ticks)
    assert set(metrics.keys()) >= {
        "win_rate", "profit_factor", "sharpe", "max_drawdown", "n_signals",
    }


# ---- snapshot serialization round-trip --------------------------------------


def test_snapshot_json_roundtrip() -> None:
    snap = _bullish_snapshot()
    blob = snapshot_to_json(snap)
    restored = snapshot_from_json(blob)
    assert restored.as_of == snap.as_of
    assert len(restored.flows) == len(snap.flows)
    assert len(restored.bulk_deals) == len(snap.bulk_deals)
    assert len(restored.block_deals) == len(snap.block_deals)
    for a, b in zip(restored.flows, snap.flows, strict=True):
        assert a == b
    for a, b in zip(restored.bulk_deals, snap.bulk_deals, strict=True):
        assert a == b
    for a, b in zip(restored.block_deals, snap.block_deals, strict=True):
        assert a == b
