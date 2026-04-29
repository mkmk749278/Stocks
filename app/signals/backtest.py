from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(slots=True)
class TradeRecord:
    entry_price: float
    exit_price: float
    side: str  # "BUY" | "SELL"


def metrics_from_trades(trades: list[TradeRecord]) -> dict[str, Any]:
    """Compute the canonical AXIOM metrics dict from a list of closed trades.

    All layers' `backtest()` methods MUST return a dict containing at least:
      win_rate, profit_factor, sharpe, max_drawdown, n_signals.
    """
    n = len(trades)
    if n == 0:
        return {
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "n_signals": 0,
        }

    rets = np.array(
        [
            (t.exit_price - t.entry_price) / t.entry_price
            if t.side == "BUY"
            else (t.entry_price - t.exit_price) / t.entry_price
            for t in trades
        ],
        dtype=float,
    )

    wins = rets[rets > 0]
    losses = rets[rets < 0]
    win_rate = float(len(wins)) / n
    profit_factor = float(wins.sum() / -losses.sum()) if losses.size and losses.sum() < 0 else (
        float("inf") if wins.sum() > 0 else 0.0
    )

    mu, sigma = float(rets.mean()), float(rets.std(ddof=1)) if n > 1 else 0.0
    sharpe = (mu / sigma) * math.sqrt(252.0) if sigma > 0 else 0.0

    equity = np.cumsum(rets)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    max_drawdown = float(drawdown.max()) if drawdown.size else 0.0

    return {
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4) if math.isfinite(profit_factor) else float("inf"),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_drawdown, 4),
        "n_signals": n,
    }


# AXIOM go-live thresholds (from spec). Used by model-validate.yml.
THRESHOLDS = {
    "win_rate": 0.58,
    "profit_factor": 1.5,
    "sharpe": 1.5,
    "max_drawdown_max": 0.20,
}


def passes_thresholds(metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if metrics.get("win_rate", 0) <= THRESHOLDS["win_rate"]:
        failures.append(f"win_rate {metrics.get('win_rate')} <= {THRESHOLDS['win_rate']}")
    if metrics.get("profit_factor", 0) <= THRESHOLDS["profit_factor"]:
        failures.append(
            f"profit_factor {metrics.get('profit_factor')} <= {THRESHOLDS['profit_factor']}"
        )
    if metrics.get("sharpe", 0) <= THRESHOLDS["sharpe"]:
        failures.append(f"sharpe {metrics.get('sharpe')} <= {THRESHOLDS['sharpe']}")
    if metrics.get("max_drawdown", 0) >= THRESHOLDS["max_drawdown_max"]:
        failures.append(
            f"max_drawdown {metrics.get('max_drawdown')} >= {THRESHOLDS['max_drawdown_max']}"
        )
    return (not failures, failures)
