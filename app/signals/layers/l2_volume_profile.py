from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.schemas.tick import TickEvent
from app.signals.backtest import TradeRecord, metrics_from_trades
from app.signals.base import Layer, LayerSignal, Vote

# tunables — calibrated for liquid NSE equity
DEFAULT_BUCKET_SIZE = 0.05               # NSE tick size for most liquid equities
VALUE_AREA_PCT = 0.70                    # canonical 70% value area
MIN_SESSION_VOLUME = 50_000              # don't vote until profile is meaningful
HVN_LVN_SMOOTH_WINDOW = 3                # bins on each side for local extrema
EDGE_TAG_TICKS = 1                       # extreme must reach within 1 tick of the edge
REJECTION_LOOKBACK_SECONDS = 90
REJECTION_MIN_TICKS = 3                  # how far price recovers from edge
EMIT_COOLDOWN_SECONDS = 60
MIN_SCORE_TO_VOTE = 55.0


@dataclass(slots=True)
class _ProfileSnapshot:
    """Computed value area & volume nodes at a point in time."""

    vpoc: float
    vah: float
    val: float
    total_volume: float
    hvn: list[float] = field(default_factory=list)
    lvn: list[float] = field(default_factory=list)


@dataclass(slots=True)
class _SymbolState:
    session_date: str = ""
    bucket_size: float = DEFAULT_BUCKET_SIZE
    histogram: dict[int, float] = field(default_factory=dict)  # bucket_idx → volume
    total_volume: float = 0.0

    # Rejection tracking: recent (ts, price) tail used to detect bounce off VAH/VAL.
    recent: list[tuple[datetime, float]] = field(default_factory=list)
    last_emit: datetime | None = None


def _bucket_index(price: float, bucket_size: float) -> int:
    return int(round(price / bucket_size))


def _bucket_price(idx: int, bucket_size: float) -> float:
    return idx * bucket_size


def compute_profile(
    histogram: dict[int, float],
    bucket_size: float,
    value_area_pct: float = VALUE_AREA_PCT,
    smooth_window: int = HVN_LVN_SMOOTH_WINDOW,
) -> _ProfileSnapshot | None:
    """Pure function: histogram → VPOC, VAH, VAL, HVN list, LVN list.

    Value area expansion is the standard market-profile algorithm: start from
    VPOC, repeatedly add the heavier of the two adjacent buckets (or pair) until
    cumulative volume reaches `value_area_pct` of total.
    """
    if not histogram:
        return None
    total = sum(histogram.values())
    if total <= 0:
        return None

    # VPOC = bucket with max volume
    vpoc_idx = max(histogram.items(), key=lambda kv: kv[1])[0]

    # Expand value area outward from VPOC
    target = total * value_area_pct
    included = {vpoc_idx}
    cum = histogram[vpoc_idx]
    upper = vpoc_idx
    lower = vpoc_idx
    while cum < target:
        up_next = histogram.get(upper + 1, 0.0)
        dn_next = histogram.get(lower - 1, 0.0)
        if up_next == 0.0 and dn_next == 0.0:
            # No more contiguous volume on either side — stop.
            break
        if up_next >= dn_next:
            upper += 1
            included.add(upper)
            cum += up_next
        else:
            lower -= 1
            included.add(lower)
            cum += dn_next

    vah_idx = max(included)
    val_idx = min(included)

    # HVN/LVN via local extrema with simple smoothing
    sorted_idx = sorted(histogram.keys())
    hvn: list[float] = []
    lvn: list[float] = []
    for i, idx in enumerate(sorted_idx):
        v = histogram[idx]
        # Need at least `smooth_window` neighbours on each side to qualify
        left = sorted_idx[max(0, i - smooth_window) : i]
        right = sorted_idx[i + 1 : i + 1 + smooth_window]
        if not left or not right:
            continue
        left_vols = [histogram[k] for k in left]
        right_vols = [histogram[k] for k in right]
        if v > max(left_vols) and v > max(right_vols):
            hvn.append(_bucket_price(idx, bucket_size))
        elif v < min(left_vols) and v < min(right_vols):
            lvn.append(_bucket_price(idx, bucket_size))

    return _ProfileSnapshot(
        vpoc=_bucket_price(vpoc_idx, bucket_size),
        vah=_bucket_price(vah_idx, bucket_size),
        val=_bucket_price(val_idx, bucket_size),
        total_volume=total,
        hvn=hvn,
        lvn=lvn,
    )


class VolumeProfileLayer(Layer):
    """Layer 2 — Volume Profile.

    Market-profile based mean-reversion at value area edges:
      * BUY when price tags VAL (or an LVN below it) and rejects upward.
      * SELL when price tags VAH (or an HVN above it) and rejects downward.

    Profile resets each session (per IST trading day) for the symbol.
    """

    name = "VOLUME_PROFILE"

    def __init__(self, bucket_size: float = DEFAULT_BUCKET_SIZE) -> None:
        self._state: dict[str, _SymbolState] = defaultdict(
            lambda: _SymbolState(bucket_size=bucket_size)
        )
        self._default_bucket = bucket_size

    # ---------- helpers ----------

    @staticmethod
    def _session_key(ts: datetime) -> str:
        return ts.strftime("%Y-%m-%d")

    def _maybe_reset_session(self, st: _SymbolState, tick: TickEvent) -> None:
        key = self._session_key(tick.ts_ist)
        if st.session_date != key:
            st.session_date = key
            st.histogram = {}
            st.total_volume = 0.0
            st.recent = []
            st.last_emit = None

    def _trim_recent(self, st: _SymbolState, now: datetime) -> None:
        cutoff = now - timedelta(seconds=REJECTION_LOOKBACK_SECONDS)
        i = 0
        for i, (t, _p) in enumerate(st.recent):
            if t >= cutoff:
                break
        if i > 0:
            del st.recent[:i]

    def _detect_rejection(
        self,
        st: _SymbolState,
        edge_price: float,
        side: str,
        bucket_size: float,
    ) -> bool:
        """Did price tag the edge in the lookback window then move away by >= REJECTION_MIN_TICKS?

        Canonical market-profile rejection:
          * VAL: min(recent) reached within EDGE_TAG_TICKS of VAL, then last price
            recovered REJECTION_MIN_TICKS above that low.
          * VAH: max(recent) reached within EDGE_TAG_TICKS of VAH, then last price
            fell REJECTION_MIN_TICKS below that high.
        """
        if len(st.recent) < 2:
            return False
        edge_band = bucket_size * EDGE_TAG_TICKS
        last_price = st.recent[-1][1]
        if side == "VAL":
            extreme = min(p for _t, p in st.recent)
            if extreme > edge_price + edge_band:
                return False  # never reached the edge
            return last_price - extreme >= bucket_size * REJECTION_MIN_TICKS
        # VAH
        extreme = max(p for _t, p in st.recent)
        if extreme < edge_price - edge_band:
            return False
        return extreme - last_price >= bucket_size * REJECTION_MIN_TICKS

    # ---------- main entry ----------

    async def on_tick(self, tick: TickEvent) -> LayerSignal | None:
        st = self._state[tick.symbol]
        self._maybe_reset_session(st, tick)

        bucket_size = st.bucket_size
        idx = _bucket_index(tick.price, bucket_size)
        st.histogram[idx] = st.histogram.get(idx, 0.0) + tick.qty
        st.total_volume += tick.qty
        st.recent.append((tick.ts_ist, tick.price))
        self._trim_recent(st, tick.ts_ist)

        if st.total_volume < MIN_SESSION_VOLUME:
            return None

        snap = compute_profile(st.histogram, bucket_size)
        if snap is None:
            return None

        # Cooldown
        if (
            st.last_emit is not None
            and (tick.ts_ist - st.last_emit).total_seconds() < EMIT_COOLDOWN_SECONDS
        ):
            return None

        # ---- evaluate edges ----
        # BUY at VAL / nearest LVN below VAL with rejection
        below_lvn = max((p for p in snap.lvn if p < snap.val), default=None)
        buy_edge = below_lvn if below_lvn is not None and tick.price <= below_lvn + bucket_size * EDGE_TAG_TICKS else snap.val

        # SELL at VAH / nearest HVN above VAH with rejection
        above_hvn = min((p for p in snap.hvn if p > snap.vah), default=None)
        sell_edge = above_hvn if above_hvn is not None and tick.price >= above_hvn - bucket_size * EDGE_TAG_TICKS else snap.vah

        vote = Vote.NONE
        score = 0.0
        edge_used: tuple[str, float] | None = None

        if self._detect_rejection(st, buy_edge, "VAL", bucket_size):
            distance = (snap.vpoc - tick.price) / max(snap.vpoc - snap.val, bucket_size)
            distance = max(0.0, min(1.5, distance))
            score = 60.0 + 40.0 * min(1.0, distance)
            vote = Vote.BUY
            edge_used = ("VAL_or_LVN", buy_edge)
        elif self._detect_rejection(st, sell_edge, "VAH", bucket_size):
            distance = (tick.price - snap.vpoc) / max(snap.vah - snap.vpoc, bucket_size)
            distance = max(0.0, min(1.5, distance))
            score = 60.0 + 40.0 * min(1.0, distance)
            vote = Vote.SELL
            edge_used = ("VAH_or_HVN", sell_edge)

        if vote is Vote.NONE or score < MIN_SCORE_TO_VOTE:
            return None

        st.last_emit = tick.ts_ist

        return LayerSignal(
            layer=self.name,
            vote=vote,
            score=round(score, 2),
            ts_ist=tick.ts_ist,
            symbol=tick.symbol,
            features={
                "vpoc": snap.vpoc,
                "vah": snap.vah,
                "val": snap.val,
                "hvn": snap.hvn[:5],
                "lvn": snap.lvn[:5],
                "edge": edge_used[0] if edge_used else None,
                "edge_price": edge_used[1] if edge_used else None,
                "session_volume": snap.total_volume,
            },
        )

    # ---------- backtest harness ----------

    def backtest(self, ticks: list[TickEvent]) -> dict[str, Any]:
        """Walk the tick list; for each emitted signal score the next 5-minute move."""
        import asyncio

        async def _run() -> list[TradeRecord]:
            self.__init__(bucket_size=self._default_bucket)
            signals: list[LayerSignal] = []
            for t in ticks:
                ls = await self.on_tick(t)
                if ls is not None:
                    signals.append(ls)
            trades: list[TradeRecord] = []
            sorted_idx = sorted(range(len(ticks)), key=lambda i: ticks[i].ts_ist)
            for ls in signals:
                entry_i = next(
                    (i for i in sorted_idx if ticks[i].ts_ist >= ls.ts_ist), None
                )
                if entry_i is None:
                    continue
                exit_ts = ls.ts_ist + timedelta(minutes=5)
                exit_i = next(
                    (i for i in sorted_idx if ticks[i].ts_ist >= exit_ts), len(ticks) - 1
                )
                trades.append(
                    TradeRecord(
                        entry_price=ticks[entry_i].price,
                        exit_price=ticks[exit_i].price,
                        side=ls.vote.value,
                    )
                )
            return trades

        return metrics_from_trades(asyncio.run(_run()))
