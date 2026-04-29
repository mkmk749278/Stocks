from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.schemas.tick import TickEvent
from app.signals.backtest import TradeRecord, metrics_from_trades
from app.signals.base import Layer, LayerSignal, Vote

# ---- domain types ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OptionContract:
    strike: float
    option_type: str           # "CE" | "PE"
    ltp: float
    oi: int
    oi_change: int             # OI change vs previous snapshot or prior session
    volume: int
    iv: float                  # implied volatility, decimal (0.18 = 18%)
    delta: float
    gamma: float
    expiry: date


@dataclass(frozen=True, slots=True)
class OptionsSnapshot:
    underlying: str            # e.g., "NIFTY", "BANKNIFTY", "RELIANCE"
    spot_at_snapshot: float
    ts_ist: datetime
    contracts: tuple[OptionContract, ...]


# ---- tunables (calibrated for NSE index options) -----------------------------

SNAPSHOT_STALENESS_SECONDS = 5 * 60      # snapshot older than this → no vote
PCR_BULLISH = 1.30                       # PCR above this is bullish (high put writing)
PCR_BEARISH = 0.70                       # PCR below this is bearish
WALL_PROXIMITY_PCT = 0.0030              # 0.30% from spot — within reach of GEX wall
UNUSUAL_OI_MULTIPLIER = 3.0              # |oi_change| > 3x median = unusual
EMIT_COOLDOWN_SECONDS = 60
MIN_SCORE_TO_VOTE = 55.0


# Equity/index symbol → option underlying name. For Nifty futures and Nifty
# spot the option underlying is "NIFTY"; same pattern for BankNifty etc.
SYMBOL_TO_UNDERLYING: dict[str, str] = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "FINNIFTY": "FINNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY",
}


# ---- pure analytics ---------------------------------------------------------


def compute_pcr(snap: OptionsSnapshot) -> float:
    """Put-Call Ratio of total open interest. >1 = more puts open than calls."""
    put_oi = sum(c.oi for c in snap.contracts if c.option_type == "PE")
    call_oi = sum(c.oi for c in snap.contracts if c.option_type == "CE")
    if call_oi == 0:
        return float("inf") if put_oi > 0 else 0.0
    return put_oi / call_oi


def compute_max_pain(snap: OptionsSnapshot) -> float:
    """Strike that minimizes total option-holder profit at expiry."""
    if not snap.contracts:
        return 0.0
    strikes = sorted({c.strike for c in snap.contracts})
    best_strike = strikes[0]
    best_pain = float("inf")
    for K in strikes:
        pain = 0.0
        for c in snap.contracts:
            if c.option_type == "CE":
                pain += max(0.0, K - c.strike) * c.oi  # call writers' loss at expiry K
            else:
                pain += max(0.0, c.strike - K) * c.oi  # put writers' loss at expiry K
        if pain < best_pain:
            best_pain = pain
            best_strike = K
    return best_strike


def compute_gex(snap: OptionsSnapshot, spot: float) -> dict[float, float]:
    """Gamma exposure per strike.

    Convention: dealers are short calls and long puts (typical retail flow into
    market makers). Resulting GEX is positive at call-heavy strikes (suppresses
    moves above) and negative at put-heavy strikes (amplifies moves below).
    """
    gex: dict[float, float] = {}
    for c in snap.contracts:
        sign = 1.0 if c.option_type == "CE" else -1.0
        contribution = sign * c.gamma * c.oi * 100 * (spot ** 2) * 0.0001
        gex[c.strike] = gex.get(c.strike, 0.0) + contribution
    return gex


def find_gex_walls(
    gex: dict[float, float], spot: float
) -> tuple[float | None, float | None]:
    """Return (resistance_strike, support_strike).

    Resistance = strike at-or-above spot with the largest positive GEX.
    Support    = strike at-or-below spot with the largest negative GEX magnitude.
    """
    above = {k: v for k, v in gex.items() if k >= spot and v > 0.0}
    below = {k: v for k, v in gex.items() if k <= spot and v < 0.0}
    resistance = max(above.items(), key=lambda kv: kv[1])[0] if above else None
    support = min(below.items(), key=lambda kv: kv[1])[0] if below else None
    return resistance, support


def compute_iv_skew(snap: OptionsSnapshot, spot: float) -> float:
    """Average OTM-put IV minus average OTM-call IV.

    Positive = put skew (fear / hedge demand). Negative = call skew (chase).
    """
    puts = [c.iv for c in snap.contracts if c.option_type == "PE" and c.strike < spot]
    calls = [c.iv for c in snap.contracts if c.option_type == "CE" and c.strike > spot]
    if not puts or not calls:
        return 0.0
    return sum(puts) / len(puts) - sum(calls) / len(calls)


def find_unusual_oi(
    snap: OptionsSnapshot, multiplier: float = UNUSUAL_OI_MULTIPLIER
) -> list[tuple[float, str, int]]:
    """Strikes whose |oi_change| exceeds `multiplier` × median |oi_change|."""
    changes = [abs(c.oi_change) for c in snap.contracts if c.oi_change != 0]
    if not changes:
        return []
    sorted_c = sorted(changes)
    median = sorted_c[len(sorted_c) // 2]
    if median == 0:
        return []
    threshold = multiplier * median
    return [
        (c.strike, c.option_type, c.oi_change)
        for c in snap.contracts
        if abs(c.oi_change) > threshold
    ]


# ---- layer ------------------------------------------------------------------


@dataclass(slots=True)
class _UnderlyingState:
    snapshot: OptionsSnapshot | None = None
    last_emit: datetime | None = None
    last_redis_check: datetime | None = None


REDIS_RELOAD_EVERY_SECONDS = 30


class OptionsFlowLayer(Layer):
    """Layer 3 — Options Flow.

    Combines GEX walls (gamma support / resistance), Put-Call Ratio extremes,
    IV skew direction, and unusual OI changes into a single score per side.

    Snapshots arrive via `update_snapshot(snap)` from a Celery beat task that
    polls Kite option chain. The layer caches the latest snapshot per
    underlying. `on_tick(tick)` joins the latest snapshot with the spot price
    from the equity tick and emits a vote when proximity to a wall is
    corroborated by PCR/IV skew.
    """

    name = "OPTIONS_FLOW"

    def __init__(self, redis_loader: Any | None = None) -> None:
        self._state: dict[str, _UnderlyingState] = defaultdict(_UnderlyingState)
        self._snapshots: list[OptionsSnapshot] = []  # for backtest replay
        # Optional callable: (underlying: str) -> OptionsSnapshot | None.
        # Production wiring uses a sync Redis getter; tests inject snapshots directly.
        self._redis_loader = redis_loader

    # ---- snapshot ingestion ----

    def update_snapshot(self, snap: OptionsSnapshot) -> None:
        self._state[snap.underlying].snapshot = snap

    def set_snapshots(self, snapshots: list[OptionsSnapshot]) -> None:
        """Wire a deterministic snapshot stream for tests / backtests."""
        self._snapshots = sorted(snapshots, key=lambda s: s.ts_ist)

    def _maybe_reload_from_redis(self, underlying: str, now: datetime) -> None:
        if self._redis_loader is None:
            return
        st = self._state[underlying]
        if (
            st.last_redis_check is not None
            and (now - st.last_redis_check).total_seconds() < REDIS_RELOAD_EVERY_SECONDS
        ):
            return
        st.last_redis_check = now
        try:
            snap = self._redis_loader(underlying)
        except Exception:  # noqa: BLE001
            return
        if snap is not None:
            st.snapshot = snap

    # ---- main entry ----

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:
        underlying = SYMBOL_TO_UNDERLYING.get(tick.symbol, tick.symbol)
        st = self._state[underlying]

        # advance any pre-loaded snapshots whose ts <= current tick (test/backtest path)
        if self._snapshots:
            while self._snapshots and self._snapshots[0].ts_ist <= tick.ts_ist:
                st.snapshot = self._snapshots.pop(0)
        else:
            # Production path: reload from Redis at most once per N seconds per symbol
            self._maybe_reload_from_redis(underlying, tick.ts_ist)

        snap = st.snapshot
        if snap is None or snap.underlying != underlying:
            return None
        if (tick.ts_ist - snap.ts_ist).total_seconds() > SNAPSHOT_STALENESS_SECONDS:
            return None

        if (
            st.last_emit is not None
            and (tick.ts_ist - st.last_emit).total_seconds() < EMIT_COOLDOWN_SECONDS
        ):
            return None

        spot = tick.price
        pcr = compute_pcr(snap)
        gex = compute_gex(snap, spot)
        resistance, support = find_gex_walls(gex, spot)
        skew = compute_iv_skew(snap, spot)
        unusual = find_unusual_oi(snap)
        max_pain = compute_max_pain(snap)

        # ---- proximity to walls ----
        near_support = (
            support is not None and abs(spot - support) / spot <= WALL_PROXIMITY_PCT
        )
        near_resistance = (
            resistance is not None
            and abs(resistance - spot) / spot <= WALL_PROXIMITY_PCT
        )

        # ---- corroborating signals ----
        unusual_calls_buying = sum(
            1 for s, t, c in unusual if t == "CE" and c > 0
        )
        unusual_puts_buying = sum(
            1 for s, t, c in unusual if t == "PE" and c > 0
        )

        # Weighted accumulation per side (designed so 2-3 corroborating signals
        # clear the EMIT_TOTAL threshold). IV skew is a soft modifier only.
        WALL_W = 1.0
        PCR_W = 0.8
        UNUSUAL_W = 0.5
        SKEW_W = 0.4
        EMIT_TOTAL = 1.5

        buy_total = 0.0
        sell_total = 0.0

        if near_support:
            buy_total += WALL_W
        if near_resistance:
            sell_total += WALL_W
        if pcr >= PCR_BULLISH:
            buy_total += PCR_W * min(1.0, (pcr - PCR_BULLISH) / PCR_BULLISH + 0.4)
        if 0.0 < pcr <= PCR_BEARISH:
            sell_total += PCR_W * min(1.0, (PCR_BEARISH - pcr) / PCR_BEARISH + 0.4)
        if skew > 0.02:
            buy_total += SKEW_W * min(1.0, skew * 10.0)
        elif skew < -0.02:
            sell_total += SKEW_W * min(1.0, -skew * 10.0)
        if unusual_calls_buying >= 2:
            buy_total += UNUSUAL_W * min(1.0, unusual_calls_buying / 4.0)
        if unusual_puts_buying >= 2:
            sell_total += UNUSUAL_W * min(1.0, unusual_puts_buying / 4.0)

        if buy_total >= EMIT_TOTAL and buy_total > sell_total:
            vote = Vote.BUY
            score = min(100.0, 40.0 + buy_total * 25.0)
        elif sell_total >= EMIT_TOTAL and sell_total > buy_total:
            vote = Vote.SELL
            score = min(100.0, 40.0 + sell_total * 25.0)
        else:
            return None

        if score < MIN_SCORE_TO_VOTE:
            return None

        st.last_emit = tick.ts_ist

        return LayerSignal(
            layer=self.name,
            vote=vote,
            score=round(score, 2),
            ts_ist=tick.ts_ist,
            symbol=tick.symbol,
            features={
                "underlying": underlying,
                "pcr": round(pcr, 3),
                "gex_resistance": resistance,
                "gex_support": support,
                "iv_skew": round(skew, 4),
                "unusual_oi": unusual[:8],
                "max_pain": max_pain,
                "snapshot_age_sec": int((tick.ts_ist - snap.ts_ist).total_seconds()),
            },
        )

    # ---- backtest harness ----

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:
        """Replay layer over a tick sequence; relies on snapshots wired via
        `set_snapshots()` before calling. Returns AXIOM metrics dict.
        """
        import asyncio

        async def _run() -> list[TradeRecord]:
            preserved = list(self._snapshots)  # restore after replay
            try:
                self._state.clear()
                self._snapshots = preserved.copy()
                signals: list[LayerSignal] = []
                for t in ticks:
                    ls = await self.on_tick(t)
                    if ls is not None:
                        signals.append(ls)
                trades: list[TradeRecord] = []
                idx_order = sorted(range(len(ticks)), key=lambda i: ticks[i].ts_ist)
                for ls in signals:
                    entry_i = next(
                        (i for i in idx_order if ticks[i].ts_ist >= ls.ts_ist), None
                    )
                    if entry_i is None:
                        continue
                    exit_ts = ls.ts_ist + timedelta(minutes=5)
                    exit_i = next(
                        (i for i in idx_order if ticks[i].ts_ist >= exit_ts),
                        len(ticks) - 1,
                    )
                    trades.append(
                        TradeRecord(
                            entry_price=ticks[entry_i].price,
                            exit_price=ticks[exit_i].price,
                            side=ls.vote.value,
                        )
                    )
                return trades
            finally:
                self._snapshots = preserved

        return metrics_from_trades(asyncio.run(_run()))
