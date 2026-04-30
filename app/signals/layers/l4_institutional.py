from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.schemas.tick import TickEvent
from app.signals.backtest import TradeRecord, metrics_from_trades
from app.signals.base import Layer, LayerSignal, Vote

# ---- domain types ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FlowDay:
    """One day of FII/DII flow (cash market). Values in INR crores."""

    trade_date: date
    fii_buy: float
    fii_sell: float
    dii_buy: float
    dii_sell: float

    @property
    def fii_net(self) -> float:
        return self.fii_buy - self.fii_sell

    @property
    def dii_net(self) -> float:
        return self.dii_buy - self.dii_sell

    @property
    def combined_net(self) -> float:
        return self.fii_net + self.dii_net


@dataclass(frozen=True, slots=True)
class BulkDeal:
    """NSE bulk-deal record: single client trades >= 0.5% of listed equity."""

    trade_date: date
    symbol: str
    client_name: str
    side: str            # "BUY" | "SELL"
    quantity: int
    avg_price: float


@dataclass(frozen=True, slots=True)
class BlockDeal:
    """NSE block-deal record: negotiated trade >= INR 10 crore."""

    trade_date: date
    symbol: str
    side: str
    quantity: int
    trade_price: float


@dataclass(frozen=True, slots=True)
class InstitutionalSnapshot:
    """Daily roll-up. Updated by the post-market beat task."""

    as_of: date
    flows: tuple[FlowDay, ...]                    # most-recent N days
    bulk_deals: tuple[BulkDeal, ...]              # last 5 trading days
    block_deals: tuple[BlockDeal, ...]


# ---- tunables ----------------------------------------------------------------

FLOW_WINDOW_DAYS = 5
FLOW_BIAS_BULLISH_Z = 1.0          # combined net Z above this → bullish bias
FLOW_BIAS_BEARISH_Z = -1.0
INSTITUTIONAL_KNOWN_NAMES = {
    # heuristic: names containing any of these strings are treated as
    # known institutions (mutual funds, FPIs, insurance, banks, prop desks).
    "MUTUAL FUND", "MF ", "ASSET MANAGEMENT", "AMC", "INSURANCE",
    "FPI", "PORTFOLIO", "SOCIETE GENERALE", "GOLDMAN", "MORGAN STANLEY",
    "BANK", "PROP", "TRADING LLP",
}
BLOCK_PREMIUM_PCT = 0.005          # >= 0.5% above ref price = premium
EMIT_COOLDOWN_SECONDS = 300        # 5 min — daily-data layer doesn't need fast cadence
MIN_SCORE_TO_VOTE = 55.0


# ---- pure analytics ---------------------------------------------------------


def compute_flow_bias(flows: list[FlowDay] | tuple[FlowDay, ...]) -> tuple[float, float]:
    """Return (z_score, last_net) for the last `FLOW_WINDOW_DAYS` of combined net flow.

    z_score is the latest day's combined_net standardized against the rolling
    mean and std of the window. Positive = bullish (institutions net buying).
    """
    if not flows:
        return 0.0, 0.0
    series = sorted(flows, key=lambda f: f.trade_date)[-FLOW_WINDOW_DAYS:]
    if len(series) < 2:
        return 0.0, series[-1].combined_net
    nets = [f.combined_net for f in series]
    mu = sum(nets) / len(nets)
    var = sum((x - mu) ** 2 for x in nets) / (len(nets) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return 0.0, nets[-1]
    return (nets[-1] - mu) / sd, nets[-1]


def is_known_institution(client_name: str) -> bool:
    upper = client_name.upper()
    return any(token in upper for token in INSTITUTIONAL_KNOWN_NAMES)


def aggregate_bulk_deals(deals: list[BulkDeal] | tuple[BulkDeal, ...], symbol: str) -> dict[str, int]:
    """Net institutional flow for `symbol` from bulk deals.

    Returns: {"net_qty": int (BUY-SELL), "inst_buy": int, "inst_sell": int, "n_deals": int}
    Only counts deals where the client is recognised as institutional.
    """
    inst_buy = 0
    inst_sell = 0
    n = 0
    for d in deals:
        if d.symbol.upper() != symbol.upper():
            continue
        if not is_known_institution(d.client_name):
            continue
        n += 1
        if d.side.upper() == "BUY":
            inst_buy += d.quantity
        else:
            inst_sell += d.quantity
    return {
        "net_qty": inst_buy - inst_sell,
        "inst_buy": inst_buy,
        "inst_sell": inst_sell,
        "n_deals": n,
    }


def classify_block_deal(deal: BlockDeal, ref_price: float) -> str:
    """Premium / discount / neutral relative to a reference price (e.g., session VWAP)."""
    if ref_price <= 0:
        return "neutral"
    diff = (deal.trade_price - ref_price) / ref_price
    if diff >= BLOCK_PREMIUM_PCT:
        return "premium"
    if diff <= -BLOCK_PREMIUM_PCT:
        return "discount"
    return "neutral"


def aggregate_block_deals(
    deals: list[BlockDeal] | tuple[BlockDeal, ...],
    symbol: str,
    ref_price: float,
) -> dict[str, int]:
    """Premium vs discount block-deal counts for `symbol` against a reference price."""
    premium_count = 0
    discount_count = 0
    n = 0
    for d in deals:
        if d.symbol.upper() != symbol.upper():
            continue
        n += 1
        cls = classify_block_deal(d, ref_price)
        if cls == "premium":
            premium_count += 1
        elif cls == "discount":
            discount_count += 1
    return {"premium": premium_count, "discount": discount_count, "n_deals": n}


# ---- layer ------------------------------------------------------------------


@dataclass(slots=True)
class _SymbolState:
    last_emit: datetime | None = None
    session_vwap_pv: float = 0.0
    session_vwap_vol: float = 0.0
    session_date: str = ""
    last_redis_check: datetime | None = None


REDIS_RELOAD_EVERY_SECONDS = 60


class InstitutionalLayer(Layer):
    """Layer 4 — Institutional Activity.

    Combines three positioning signals:
      1. FII/DII combined net-flow z-score over the last 5 trading days.
      2. Bulk-deal net institutional quantity for the symbol.
      3. Block-deal premium vs discount counts for the symbol.

    Daily roll-ups arrive via the beat task `app.tasks.institutional.refresh`
    and are cached in Redis. The layer reloads on demand and joins with the
    live tick price (used as a session-VWAP reference for block deal
    classification).
    """

    name = "INSTITUTIONAL"

    def __init__(self, redis_loader: Any | None = None) -> None:
        self._snapshot: InstitutionalSnapshot | None = None
        self._state: dict[str, _SymbolState] = defaultdict(_SymbolState)
        self._redis_loader = redis_loader

    # ---- snapshot ingestion ----

    def update_snapshot(self, snap: InstitutionalSnapshot) -> None:
        self._snapshot = snap

    def _maybe_reload_from_redis(self, now: datetime) -> None:
        if self._redis_loader is None:
            return
        # Use a single global reload throttle (snapshot is one-per-day, not per-symbol).
        st = self._state["__global__"]
        if (
            st.last_redis_check is not None
            and (now - st.last_redis_check).total_seconds() < REDIS_RELOAD_EVERY_SECONDS
        ):
            return
        st.last_redis_check = now
        try:
            snap = self._redis_loader()
        except Exception:  # noqa: BLE001
            return
        if snap is not None:
            self._snapshot = snap

    # ---- VWAP (session) ----

    def _update_vwap(self, st: _SymbolState, tick: TickEvent) -> float:
        date_str = tick.ts_ist.strftime("%Y-%m-%d")
        if st.session_date != date_str:
            st.session_date = date_str
            st.session_vwap_pv = 0.0
            st.session_vwap_vol = 0.0
        st.session_vwap_pv += tick.price * tick.qty
        st.session_vwap_vol += tick.qty
        return st.session_vwap_pv / st.session_vwap_vol if st.session_vwap_vol else tick.price

    # ---- main entry ----

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:
        st = self._state[tick.symbol]
        self._maybe_reload_from_redis(tick.ts_ist)

        snap = self._snapshot
        if snap is None:
            return None
        # Bail if the snapshot is older than 2 trading days — likely stale.
        if (tick.ts_ist.date() - snap.as_of).days > 2:
            return None

        if (
            st.last_emit is not None
            and (tick.ts_ist - st.last_emit).total_seconds() < EMIT_COOLDOWN_SECONDS
        ):
            return None

        vwap = self._update_vwap(st, tick)
        z, last_net = compute_flow_bias(list(snap.flows))
        bulk = aggregate_bulk_deals(list(snap.bulk_deals), tick.symbol)
        block = aggregate_block_deals(list(snap.block_deals), tick.symbol, vwap)

        # ---- weighted accumulation per side ----
        FLOW_W = 0.9
        BULK_W = 1.0
        BLOCK_W = 0.7
        EMIT_TOTAL = 1.4

        buy_total = 0.0
        sell_total = 0.0

        if z >= FLOW_BIAS_BULLISH_Z:
            buy_total += FLOW_W * min(1.0, (z - FLOW_BIAS_BULLISH_Z) / FLOW_BIAS_BULLISH_Z + 0.5)
        elif z <= FLOW_BIAS_BEARISH_Z:
            sell_total += FLOW_W * min(1.0, (FLOW_BIAS_BEARISH_Z - z) / abs(FLOW_BIAS_BEARISH_Z) + 0.5)

        if bulk["n_deals"] > 0 and bulk["net_qty"] != 0:
            mag = abs(bulk["net_qty"]) / max(1, bulk["inst_buy"] + bulk["inst_sell"])
            if bulk["net_qty"] > 0:
                buy_total += BULK_W * min(1.0, mag + 0.4)
            else:
                sell_total += BULK_W * min(1.0, mag + 0.4)

        if block["premium"] > block["discount"] and block["premium"] >= 1:
            buy_total += BLOCK_W * min(1.0, (block["premium"] - block["discount"]) / 3.0 + 0.5)
        elif block["discount"] > block["premium"] and block["discount"] >= 1:
            sell_total += BLOCK_W * min(1.0, (block["discount"] - block["premium"]) / 3.0 + 0.5)

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
                "flow_z": round(z, 3),
                "last_combined_net_cr": round(last_net, 2),
                "bulk_net_qty": bulk["net_qty"],
                "bulk_n_deals": bulk["n_deals"],
                "block_premium": block["premium"],
                "block_discount": block["discount"],
                "session_vwap": round(vwap, 2),
                "as_of": snap.as_of.isoformat(),
            },
        )

    # ---- backtest harness ----

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:
        """Replay over a tick sequence. Caller must `update_snapshot()` first."""
        import asyncio

        async def _run() -> list[TradeRecord]:
            saved_snap = self._snapshot
            self._state.clear()
            try:
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
                    exit_ts = ls.ts_ist + timedelta(minutes=15)
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
                self._snapshot = saved_snap

        return metrics_from_trades(asyncio.run(_run()))
