"""Periodic option-chain fetcher.

Runs as a Celery beat task every minute during NSE F&O market hours. Pulls the
relevant strikes for each tracked index from Kite REST, constructs an
OptionsSnapshot, and caches it in Redis under
`axiom:options_snapshot:<UNDERLYING>` with a 3-minute TTL.

The L3 OptionsFlowLayer reads from this Redis cache on demand (see
`OptionsFlowLayer._maybe_reload_from_redis`).
"""
from __future__ import annotations

from datetime import date
from typing import Any

import redis as sync_redis

from app.celery_app import celery_app
from app.config import get_settings
from app.logger import get_logger
from app.options_chain_io import (
    REDIS_KEY_FMT,
    SNAPSHOT_TTL_SECONDS,
    snapshot_from_json,
    snapshot_to_json,
)
from app.signals.layers.l3_options_flow import OptionContract, OptionsSnapshot
from app.timeutil import market_open, now_ist

log = get_logger(__name__)

TRACKED_UNDERLYINGS = ("NIFTY", "BANKNIFTY", "FINNIFTY")
STRIKES_AROUND_SPOT = 12

__all__ = [
    "REDIS_KEY_FMT",
    "SNAPSHOT_TTL_SECONDS",
    "TRACKED_UNDERLYINGS",
    "snapshot_from_json",
    "snapshot_to_json",
    "refresh_options_snapshots",
]


def _build_snapshot_from_kite(underlying: str) -> OptionsSnapshot | None:
    """Pull the current chain for `underlying` from Kite REST and build a snapshot.

    Returns None if Kite credentials aren't configured (offline / dev VPS).
    Concrete REST calls are deferred to the layer that can actually contact
    Kite — this scaffold is enough to drive scheduling and Redis caching.
    """
    s = get_settings()
    if not (s.kite_api_key and s.kite_access_token):
        return None
    try:
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=s.kite_api_key)
        kite.set_access_token(s.kite_access_token)

        ltp = kite.ltp([f"NSE:{underlying} 50"]) if underlying == "NIFTY" else kite.ltp(
            [f"NSE:{underlying}"]
        )
        spot = next(iter(ltp.values()))["last_price"] if ltp else 0.0

        # Discover NFO instruments for this underlying with the nearest expiry.
        instruments: list[dict[str, Any]] = kite.instruments("NFO")
        relevant = [
            i for i in instruments if i.get("name") == underlying and i.get("instrument_type") in {"CE", "PE"}
        ]
        if not relevant:
            return None
        nearest_expiry = min(i["expiry"] for i in relevant)
        relevant = [i for i in relevant if i["expiry"] == nearest_expiry]

        # Pick strikes within ±STRIKES_AROUND_SPOT of spot.
        strikes_sorted = sorted({i["strike"] for i in relevant})
        atm_idx = min(
            range(len(strikes_sorted)),
            key=lambda i: abs(strikes_sorted[i] - spot),
        )
        lo = max(0, atm_idx - STRIKES_AROUND_SPOT)
        hi = min(len(strikes_sorted), atm_idx + STRIKES_AROUND_SPOT + 1)
        wanted_strikes = set(strikes_sorted[lo:hi])
        wanted = [i for i in relevant if i["strike"] in wanted_strikes]

        symbols = [f"NFO:{i['tradingsymbol']}" for i in wanted]
        quotes = kite.quote(symbols)
        contracts: list[OptionContract] = []
        for i in wanted:
            q = quotes.get(f"NFO:{i['tradingsymbol']}")
            if not q:
                continue
            contracts.append(
                OptionContract(
                    strike=float(i["strike"]),
                    option_type=i["instrument_type"],
                    ltp=float(q.get("last_price", 0.0)),
                    oi=int(q.get("oi", 0)),
                    oi_change=int(q.get("oi_day_high", 0)) - int(q.get("oi_day_low", 0)),
                    volume=int(q.get("volume", 0)),
                    iv=float(q.get("implied_volatility", 0.0)) / 100.0,
                    delta=float(q.get("greek_delta", 0.0)),
                    gamma=float(q.get("greek_gamma", 0.0)),
                    expiry=nearest_expiry if isinstance(nearest_expiry, date) else date.fromisoformat(str(nearest_expiry)),
                )
            )
        if not contracts:
            return None
        return OptionsSnapshot(
            underlying=underlying,
            spot_at_snapshot=float(spot),
            ts_ist=now_ist(),
            contracts=tuple(contracts),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("kite_options_fetch_failed", underlying=underlying, err=str(exc))
        return None


@celery_app.task(name="app.tasks.options_chain.refresh_options_snapshots")
def refresh_options_snapshots() -> dict[str, int]:
    """Fetch chain for each tracked underlying; cache JSON in Redis."""
    if not market_open():
        return {"skipped": 1}
    s = get_settings()
    r = sync_redis.from_url(s.redis_url, decode_responses=True)
    written = 0
    for under in TRACKED_UNDERLYINGS:
        snap = _build_snapshot_from_kite(under)
        if snap is None:
            continue
        r.set(REDIS_KEY_FMT.format(underlying=under), snapshot_to_json(snap), ex=SNAPSHOT_TTL_SECONDS)
        written += 1
    return {"written": written}
