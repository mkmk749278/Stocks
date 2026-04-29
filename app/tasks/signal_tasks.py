from __future__ import annotations

import asyncio
from typing import Any

from app.celery_app import celery_app
from app.logger import get_logger
from app.schemas.tick import TickEvent
from app.signals.aggregator import SignalAggregator
from app.signals.base import AggregatedSignal
from app.signals.registry import build_layers
from app.timeutil import IST, now_ist

log = get_logger(__name__)

_LAYERS = build_layers()
_AGGREGATOR = SignalAggregator()


def _tick_from_dict(d: dict[str, Any]) -> TickEvent:
    from datetime import datetime

    ts = d["ts_ist"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    if ts.tzinfo is None:
        ts = IST.localize(ts)
    return TickEvent(
        symbol=d["symbol"],
        kite_token=int(d["kite_token"]),
        ts_ist=ts,
        price=float(d["price"]),
        qty=int(d["qty"]),
        side=d.get("side", "NEUT"),
        bid=d.get("bid"),
        ask=d.get("ask"),
        bid_qty=d.get("bid_qty"),
        ask_qty=d.get("ask_qty"),
    )


async def _process_tick(tick: TickEvent) -> AggregatedSignal | None:
    aggregated: AggregatedSignal | None = None
    for layer in _LAYERS:
        try:
            sig = await layer.on_tick(tick)
        except NotImplementedError:
            continue
        except Exception as exc:  # noqa: BLE001
            log.warning("layer_on_tick_failed", layer=layer.name, err=str(exc))
            continue
        if sig is None:
            continue
        out = _AGGREGATOR.ingest(sig)
        if out is not None:
            aggregated = out
    return aggregated


@celery_app.task(name="app.tasks.signal_tasks.process_tick", bind=True, max_retries=3)
def process_tick(self: Any, payload: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ARG001
    tick = _tick_from_dict(payload)
    agg = asyncio.run(_process_tick(tick))
    if agg is None:
        return None
    return {
        "symbol": agg.symbol,
        "side": agg.side.value,
        "confidence": agg.confidence,
        "regime": agg.regime,
        "layers_voted": agg.layers_voted,
        "ts_ist": agg.ts_ist.isoformat(),
        "breakdown": agg.breakdown,
    }


@celery_app.task(name="app.tasks.signal_tasks.heartbeat")
def heartbeat() -> str:
    return now_ist().isoformat()
