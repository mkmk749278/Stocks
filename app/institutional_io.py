"""Pure (de)serialization helpers for InstitutionalSnapshot. No Celery import."""
from __future__ import annotations

import json
from datetime import date

from app.signals.layers.l4_institutional import (
    BlockDeal,
    BulkDeal,
    FlowDay,
    InstitutionalSnapshot,
)

REDIS_KEY = "axiom:institutional:latest"
SNAPSHOT_TTL_SECONDS = 36 * 60 * 60  # 36h: covers a non-trading day plus margin


def snapshot_to_json(snap: InstitutionalSnapshot) -> str:
    return json.dumps(
        {
            "as_of": snap.as_of.isoformat(),
            "flows": [
                {
                    "trade_date": f.trade_date.isoformat(),
                    "fii_buy": f.fii_buy,
                    "fii_sell": f.fii_sell,
                    "dii_buy": f.dii_buy,
                    "dii_sell": f.dii_sell,
                }
                for f in snap.flows
            ],
            "bulk_deals": [
                {
                    "trade_date": d.trade_date.isoformat(),
                    "symbol": d.symbol,
                    "client_name": d.client_name,
                    "side": d.side,
                    "quantity": d.quantity,
                    "avg_price": d.avg_price,
                }
                for d in snap.bulk_deals
            ],
            "block_deals": [
                {
                    "trade_date": d.trade_date.isoformat(),
                    "symbol": d.symbol,
                    "side": d.side,
                    "quantity": d.quantity,
                    "trade_price": d.trade_price,
                }
                for d in snap.block_deals
            ],
        }
    )


def snapshot_from_json(blob: str) -> InstitutionalSnapshot:
    d = json.loads(blob)
    flows = tuple(
        FlowDay(
            trade_date=date.fromisoformat(f["trade_date"]),
            fii_buy=float(f["fii_buy"]),
            fii_sell=float(f["fii_sell"]),
            dii_buy=float(f["dii_buy"]),
            dii_sell=float(f["dii_sell"]),
        )
        for f in d["flows"]
    )
    bulk = tuple(
        BulkDeal(
            trade_date=date.fromisoformat(b["trade_date"]),
            symbol=b["symbol"],
            client_name=b["client_name"],
            side=b["side"],
            quantity=int(b["quantity"]),
            avg_price=float(b["avg_price"]),
        )
        for b in d["bulk_deals"]
    )
    block = tuple(
        BlockDeal(
            trade_date=date.fromisoformat(b["trade_date"]),
            symbol=b["symbol"],
            side=b["side"],
            quantity=int(b["quantity"]),
            trade_price=float(b["trade_price"]),
        )
        for b in d["block_deals"]
    )
    return InstitutionalSnapshot(
        as_of=date.fromisoformat(d["as_of"]),
        flows=flows,
        bulk_deals=bulk,
        block_deals=block,
    )
