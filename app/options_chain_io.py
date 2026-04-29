"""Pure (de)serialization helpers for OptionsSnapshot. No Celery import."""
from __future__ import annotations

import json
from datetime import date, datetime

from app.signals.layers.l3_options_flow import OptionContract, OptionsSnapshot
from app.timeutil import IST

REDIS_KEY_FMT = "axiom:options_snapshot:{underlying}"
SNAPSHOT_TTL_SECONDS = 180


def snapshot_to_json(snap: OptionsSnapshot) -> str:
    return json.dumps(
        {
            "underlying": snap.underlying,
            "spot_at_snapshot": snap.spot_at_snapshot,
            "ts_ist": snap.ts_ist.isoformat(),
            "contracts": [
                {
                    "strike": c.strike,
                    "option_type": c.option_type,
                    "ltp": c.ltp,
                    "oi": c.oi,
                    "oi_change": c.oi_change,
                    "volume": c.volume,
                    "iv": c.iv,
                    "delta": c.delta,
                    "gamma": c.gamma,
                    "expiry": c.expiry.isoformat(),
                }
                for c in snap.contracts
            ],
        }
    )


def snapshot_from_json(blob: str) -> OptionsSnapshot:
    d = json.loads(blob)
    contracts = tuple(
        OptionContract(
            strike=float(c["strike"]),
            option_type=c["option_type"],
            ltp=float(c["ltp"]),
            oi=int(c["oi"]),
            oi_change=int(c["oi_change"]),
            volume=int(c["volume"]),
            iv=float(c["iv"]),
            delta=float(c["delta"]),
            gamma=float(c["gamma"]),
            expiry=date.fromisoformat(c["expiry"]),
        )
        for c in d["contracts"]
    )
    ts = datetime.fromisoformat(d["ts_ist"])
    if ts.tzinfo is None:
        ts = IST.localize(ts)
    return OptionsSnapshot(
        underlying=d["underlying"],
        spot_at_snapshot=float(d["spot_at_snapshot"]),
        ts_ist=ts,
        contracts=contracts,
    )
