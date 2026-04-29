from __future__ import annotations

from app.signals.backtest import TradeRecord, metrics_from_trades, passes_thresholds


def test_empty_trades_zero_metrics() -> None:
    m = metrics_from_trades([])
    assert m["n_signals"] == 0
    assert m["win_rate"] == 0.0
    assert m["profit_factor"] == 0.0


def test_all_winners_high_pf() -> None:
    trades = [TradeRecord(100.0, 102.0, "BUY") for _ in range(20)]
    m = metrics_from_trades(trades)
    assert m["win_rate"] == 1.0
    assert m["profit_factor"] == float("inf")
    assert m["max_drawdown"] == 0.0


def test_mixed_trades_win_rate_correct() -> None:
    trades = (
        [TradeRecord(100.0, 102.0, "BUY") for _ in range(7)]
        + [TradeRecord(100.0, 99.0, "BUY") for _ in range(3)]
    )
    m = metrics_from_trades(trades)
    assert m["n_signals"] == 10
    assert abs(m["win_rate"] - 0.7) < 1e-9
    assert m["profit_factor"] > 1.0


def test_threshold_check_rejects_underperformer() -> None:
    metrics = {
        "win_rate": 0.50,
        "profit_factor": 1.1,
        "sharpe": 0.8,
        "max_drawdown": 0.30,
        "n_signals": 100,
    }
    ok, failures = passes_thresholds(metrics)
    assert ok is False
    assert any("win_rate" in f for f in failures)
    assert any("max_drawdown" in f for f in failures)


def test_threshold_check_accepts_strong_layer() -> None:
    metrics = {
        "win_rate": 0.62,
        "profit_factor": 1.8,
        "sharpe": 1.7,
        "max_drawdown": 0.12,
        "n_signals": 200,
    }
    ok, failures = passes_thresholds(metrics)
    assert ok is True
    assert failures == []
