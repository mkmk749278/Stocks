from __future__ import annotations

from datetime import datetime, timedelta

from app.signals.aggregator import SignalAggregator
from app.signals.base import LayerSignal, Vote
from app.timeutil import IST


def _ls(layer: str, vote: Vote, ts: datetime, score: float = 80.0) -> LayerSignal:
    return LayerSignal(
        layer=layer, vote=vote, score=score, ts_ist=ts, symbol="RELIANCE", features={}
    )


def test_under_threshold_does_not_fire() -> None:
    agg = SignalAggregator(min_layers=3, window_seconds=60)
    t0 = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    assert agg.ingest(_ls("ORDER_FLOW", Vote.BUY, t0)) is None
    assert agg.ingest(_ls("OPTIONS_FLOW", Vote.BUY, t0 + timedelta(seconds=5))) is None


def test_three_agreeing_layers_fire_with_weighted_confidence() -> None:
    agg = SignalAggregator(min_layers=3, window_seconds=60)
    t0 = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    agg.ingest(_ls("ORDER_FLOW", Vote.BUY, t0, score=70.0))
    agg.ingest(_ls("OPTIONS_FLOW", Vote.BUY, t0 + timedelta(seconds=5), score=80.0))
    out = agg.ingest(_ls("ML_MODELS", Vote.BUY, t0 + timedelta(seconds=10), score=90.0))

    assert out is not None
    assert out.side is Vote.BUY
    assert out.layers_voted == 3
    assert 70.0 < out.confidence < 90.0  # weighted average
    assert "ORDER_FLOW" in out.breakdown


def test_disagreeing_votes_do_not_count() -> None:
    agg = SignalAggregator(min_layers=3, window_seconds=60)
    t0 = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    agg.ingest(_ls("ORDER_FLOW", Vote.BUY, t0))
    agg.ingest(_ls("OPTIONS_FLOW", Vote.SELL, t0 + timedelta(seconds=5)))
    assert agg.ingest(_ls("ML_MODELS", Vote.BUY, t0 + timedelta(seconds=10))) is None


def test_window_expiry_drops_old_votes() -> None:
    agg = SignalAggregator(min_layers=3, window_seconds=60)
    t0 = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    agg.ingest(_ls("ORDER_FLOW", Vote.BUY, t0))
    agg.ingest(_ls("OPTIONS_FLOW", Vote.BUY, t0 + timedelta(seconds=5)))
    # well past the 60s window
    out = agg.ingest(_ls("ML_MODELS", Vote.BUY, t0 + timedelta(seconds=120)))
    assert out is None


def test_same_layer_replaces_prior_signal() -> None:
    agg = SignalAggregator(min_layers=3, window_seconds=60)
    t0 = IST.localize(datetime(2026, 5, 4, 10, 0, 0))
    agg.ingest(_ls("ORDER_FLOW", Vote.BUY, t0, score=10))
    agg.ingest(_ls("ORDER_FLOW", Vote.BUY, t0 + timedelta(seconds=5), score=99))
    agg.ingest(_ls("OPTIONS_FLOW", Vote.BUY, t0 + timedelta(seconds=10), score=80))
    out = agg.ingest(_ls("ML_MODELS", Vote.BUY, t0 + timedelta(seconds=15), score=80))
    assert out is not None
    # confidence should reflect the *replacement* (99) not the original (10)
    assert out.confidence > 80.0
