from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.schemas.tick import TickEvent
from app.signals.backtest import TradeRecord, metrics_from_trades
from app.signals.base import Layer, LayerSignal, Vote


@dataclass(slots=True)
class _SymbolState:
    """Per-symbol rolling state for Order Flow analytics.

    Bars are 1-minute. Sub-signals:
      * Cumulative Delta (CVD)         — running buy_vol - sell_vol
      * Absorption                     — large aggressive print, no price move
      * Footprint imbalance            — bid-stacked vs ask-stacked at touch
      * VWAP deviation (z-score)       — session VWAP via Welford-like running variance
    """

    cvd: float = 0.0
    cvd_history: deque[float] = field(default_factory=lambda: deque(maxlen=240))  # 4h @ 1/min
    absorption_events: deque[tuple[datetime, str]] = field(default_factory=lambda: deque(maxlen=20))

    # session VWAP accumulators (reset per trading day)
    vwap_session_date: str = ""
    vwap_pv: float = 0.0
    vwap_vol: float = 0.0
    # running squared deviations for variance estimate
    vwap_m2: float = 0.0
    vwap_n: int = 0

    # last bar tracking for absorption detection
    bar_ts: datetime | None = None
    bar_open: float = 0.0
    bar_high: float = -math.inf
    bar_low: float = math.inf
    bar_close: float = 0.0
    bar_buy_vol: float = 0.0
    bar_sell_vol: float = 0.0

    last_emit: datetime | None = None


# tunable thresholds — calibrated to NSE liquid equity microstructure
ABSORPTION_QTY_PERCENTILE = 0.95
ABSORPTION_MIN_PRINTS = 3
FOOTPRINT_IMBALANCE_RATIO = 3.0
VWAP_Z_TRIGGER = 2.0
CVD_DIVERGENCE_BARS = 5
EMIT_COOLDOWN_SECONDS = 30
MIN_SCORE_TO_VOTE = 55.0


class OrderFlowLayer(Layer):
    """Layer 1 — Order Flow.

    Combines four micro-features into a single 0–100 conviction score per side.
    Emits a LayerSignal only when score >= MIN_SCORE_TO_VOTE and cooldown passed.
    """

    name = "ORDER_FLOW"

    def __init__(self) -> None:
        self._state: dict[str, _SymbolState] = defaultdict(_SymbolState)
        self._recent_qtys: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=500))

    # ---------- bar bookkeeping ----------

    @staticmethod
    def _bar_floor(ts: datetime) -> datetime:
        return ts.replace(second=0, microsecond=0)

    def _roll_bar_if_needed(self, st: _SymbolState, tick: TickEvent) -> None:
        bar_ts = self._bar_floor(tick.ts_ist)
        if st.bar_ts is None:
            st.bar_ts = bar_ts
            st.bar_open = tick.price
            st.bar_high = tick.price
            st.bar_low = tick.price
            st.bar_close = tick.price
            return
        if bar_ts != st.bar_ts:
            # finalize CVD bar contribution
            st.cvd_history.append(st.cvd)
            # reset bar accumulators for the new bar
            st.bar_ts = bar_ts
            st.bar_open = tick.price
            st.bar_high = tick.price
            st.bar_low = tick.price
            st.bar_close = tick.price
            st.bar_buy_vol = 0.0
            st.bar_sell_vol = 0.0

    # ---------- feature builders ----------

    def _update_session_vwap(self, st: _SymbolState, tick: TickEvent) -> float:
        date_str = tick.ts_ist.strftime("%Y-%m-%d")
        if st.vwap_session_date != date_str:
            st.vwap_session_date = date_str
            st.vwap_pv = 0.0
            st.vwap_vol = 0.0
            st.vwap_m2 = 0.0
            st.vwap_n = 0

        st.vwap_pv += tick.price * tick.qty
        st.vwap_vol += tick.qty
        st.vwap_n += 1
        # online variance of (price - vwap_so_far)
        if st.vwap_vol > 0:
            vwap = st.vwap_pv / st.vwap_vol
            delta = tick.price - vwap
            st.vwap_m2 += delta * delta
        return st.vwap_pv / st.vwap_vol if st.vwap_vol else tick.price

    def _vwap_zscore(self, st: _SymbolState, price: float, vwap: float) -> float:
        if st.vwap_n < 30:
            return 0.0
        var = st.vwap_m2 / st.vwap_n
        sd = math.sqrt(var) if var > 0 else 0.0
        return (price - vwap) / sd if sd > 0 else 0.0

    def _footprint_imbalance(self, tick: TickEvent) -> float:
        """+ve number → ask-stacked (bullish); -ve → bid-stacked (bearish)."""
        bq = tick.bid_qty or 0
        aq = tick.ask_qty or 0
        if bq <= 0 and aq <= 0:
            return 0.0
        if bq <= 0:
            return float("inf")
        if aq <= 0:
            return -float("inf")
        return aq / bq if aq >= bq else -(bq / aq)

    def _absorption_hit(self, st: _SymbolState, tick: TickEvent) -> str | None:
        """Detect absorption: large aggressive prints (top 5%) with little price progression
        across the current bar."""
        recent = self._recent_qtys[tick.symbol]
        recent.append(int(tick.qty))
        if len(recent) < 50:
            return None
        sorted_q = sorted(recent)
        p95 = sorted_q[int(len(sorted_q) * ABSORPTION_QTY_PERCENTILE)]
        if tick.qty < p95:
            return None
        bar_range = max(0.0, st.bar_high - st.bar_low)
        # absorbed if bar range is < 0.05% of price
        if st.bar_open and bar_range / st.bar_open < 0.0005:
            # large BUY absorbed → bullish accumulation by bid; large SELL absorbed → bearish dist
            return tick.side if tick.side in {"BUY", "SELL"} else None
        return None

    # ---------- main entry ----------

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:
        st = self._state[tick.symbol]
        self._roll_bar_if_needed(st, tick)

        # bar accumulators
        st.bar_high = max(st.bar_high, tick.price)
        st.bar_low = min(st.bar_low, tick.price)
        st.bar_close = tick.price
        if tick.side == "BUY":
            st.bar_buy_vol += tick.qty
            st.cvd += tick.qty
        elif tick.side == "SELL":
            st.bar_sell_vol += tick.qty
            st.cvd -= tick.qty

        vwap = self._update_session_vwap(st, tick)
        z = self._vwap_zscore(st, tick.price, vwap)
        fp = self._footprint_imbalance(tick)
        abs_side = self._absorption_hit(st, tick)
        if abs_side:
            st.absorption_events.append((tick.ts_ist, abs_side))

        # ---- score each sub-signal in [0,1] ----
        # CVD slope across the last N bars relative to standard deviation
        cvd_score_buy = 0.0
        cvd_score_sell = 0.0
        if len(st.cvd_history) >= CVD_DIVERGENCE_BARS:
            window = list(st.cvd_history)[-CVD_DIVERGENCE_BARS:]
            slope = (window[-1] - window[0]) / CVD_DIVERGENCE_BARS
            sd = (sum((x - sum(window) / len(window)) ** 2 for x in window) / len(window)) ** 0.5
            norm = abs(slope) / sd if sd > 0 else 0.0
            mag = min(1.0, norm / 2.0)
            if slope > 0:
                cvd_score_buy = mag
            else:
                cvd_score_sell = mag

        # Absorption recency in the last 60s
        cutoff = tick.ts_ist - timedelta(seconds=60)
        recent_abs = [s for t, s in st.absorption_events if t >= cutoff]
        abs_buy = sum(1 for s in recent_abs if s == "BUY")
        abs_sell = sum(1 for s in recent_abs if s == "SELL")
        abs_score_buy = min(1.0, abs_buy / ABSORPTION_MIN_PRINTS)
        abs_score_sell = min(1.0, abs_sell / ABSORPTION_MIN_PRINTS)

        # Footprint imbalance
        fp_score_buy = 0.0
        fp_score_sell = 0.0
        if math.isfinite(fp):
            if fp > FOOTPRINT_IMBALANCE_RATIO:
                fp_score_buy = min(1.0, (fp - FOOTPRINT_IMBALANCE_RATIO) / FOOTPRINT_IMBALANCE_RATIO)
            elif fp < -FOOTPRINT_IMBALANCE_RATIO:
                fp_score_sell = min(1.0, (-fp - FOOTPRINT_IMBALANCE_RATIO) / FOOTPRINT_IMBALANCE_RATIO)
        else:
            (fp_score_buy if fp == float("inf") else fp_score_sell)  # type: ignore[func-returns-value]
            if fp == float("inf"):
                fp_score_buy = 1.0
            else:
                fp_score_sell = 1.0

        # VWAP deviation: extreme negative z-score → mean-reversion BUY; extreme positive → SELL
        vwap_score_buy = 0.0
        vwap_score_sell = 0.0
        if z <= -VWAP_Z_TRIGGER:
            vwap_score_buy = min(1.0, (abs(z) - VWAP_Z_TRIGGER) / VWAP_Z_TRIGGER + 0.5)
        elif z >= VWAP_Z_TRIGGER:
            vwap_score_sell = min(1.0, (z - VWAP_Z_TRIGGER) / VWAP_Z_TRIGGER + 0.5)

        # weighted combine
        weights = {"cvd": 0.30, "abs": 0.30, "fp": 0.20, "vwap": 0.20}
        buy_raw = (
            weights["cvd"] * cvd_score_buy
            + weights["abs"] * abs_score_buy
            + weights["fp"] * fp_score_buy
            + weights["vwap"] * vwap_score_buy
        )
        sell_raw = (
            weights["cvd"] * cvd_score_sell
            + weights["abs"] * abs_score_sell
            + weights["fp"] * fp_score_sell
            + weights["vwap"] * vwap_score_sell
        )

        if buy_raw > sell_raw:
            vote, score = Vote.BUY, buy_raw * 100.0
        elif sell_raw > buy_raw:
            vote, score = Vote.SELL, sell_raw * 100.0
        else:
            return None

        if score < MIN_SCORE_TO_VOTE:
            return None

        if (
            st.last_emit is not None
            and (tick.ts_ist - st.last_emit).total_seconds() < EMIT_COOLDOWN_SECONDS
        ):
            return None
        st.last_emit = tick.ts_ist

        return LayerSignal(
            layer=self.name,
            vote=vote,
            score=round(score, 2),
            ts_ist=tick.ts_ist,
            symbol=tick.symbol,
            features={
                "cvd": st.cvd,
                "vwap": vwap,
                "vwap_z": round(z, 3),
                "footprint": fp if math.isfinite(fp) else None,
                "absorption_recent": {"BUY": abs_buy, "SELL": abs_sell},
            },
        )

    # ---------- backtest harness ----------

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:
        """Walk the tick list, emit signals via on_tick (sync-driven), and score
        the next 5-minute price move as a trade outcome.
        """
        import asyncio

        async def _run() -> list[TradeRecord]:
            self.__init__()  # reset state
            signals: list[LayerSignal] = []
            for t in ticks:
                ls = await self.on_tick(t)
                if ls is not None:
                    signals.append(ls)
            trades: list[TradeRecord] = []
            tick_index_by_ts = sorted(range(len(ticks)), key=lambda i: ticks[i].ts_ist)
            for ls in signals:
                # find tick index at signal time
                entry_i = next(
                    (i for i in tick_index_by_ts if ticks[i].ts_ist >= ls.ts_ist), None
                )
                if entry_i is None:
                    continue
                entry_price = ticks[entry_i].price
                exit_ts = ls.ts_ist + timedelta(minutes=5)
                exit_i = next(
                    (i for i in tick_index_by_ts if ticks[i].ts_ist >= exit_ts), len(ticks) - 1
                )
                trades.append(
                    TradeRecord(
                        entry_price=entry_price,
                        exit_price=ticks[exit_i].price,
                        side=ls.vote.value,
                    )
                )
            return trades

        trades = asyncio.run(_run())
        return metrics_from_trades(trades)
