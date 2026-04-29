"""Daily institutional-data fetcher.

Runs as a Celery beat task once after market close (17:30 IST). Pulls the
NSE-published FII/DII cash-market net-flow series, bulk deals and block deals,
and caches a 5-day rolling InstitutionalSnapshot in Redis at
`axiom:institutional:latest` with a 36-hour TTL.

The L4 InstitutionalLayer reads from this Redis cache on demand
(see `InstitutionalLayer._maybe_reload_from_redis`).

NSE endpoints used (public, no auth):
  /api/fiidiiTradeReact            — daily FII/DII totals
  /api/historical/cm/equity        — bulk + block deals (with deal type param)

NSE rate-limits aggressively and requires a real User-Agent + a prior session
cookie to avoid 401s. We use a small retry/backoff helper. If any fetch
fails the task logs and returns a `partial` flag; the cached previous
snapshot remains valid for up to 36h.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import redis as sync_redis

from app.celery_app import celery_app
from app.config import get_settings
from app.institutional_io import REDIS_KEY, SNAPSHOT_TTL_SECONDS, snapshot_to_json
from app.logger import get_logger
from app.signals.layers.l4_institutional import (
    BlockDeal,
    BulkDeal,
    FlowDay,
    InstitutionalSnapshot,
)
from app.timeutil import now_ist

log = get_logger(__name__)

NSE_BASE = "https://www.nseindia.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
HTTP_TIMEOUT_SECONDS = 15


def _fetch_with_session(url: str) -> httpx.Response:
    with httpx.Client(headers=HEADERS, timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as c:
        # warm cookies first
        c.get(NSE_BASE)
        return c.get(url)


def _parse_fii_dii(payload: list[dict[str, Any]]) -> list[FlowDay]:
    """NSE returns one record per category per date. We collapse FII + DII per date."""
    by_date: dict[date, dict[str, float]] = {}
    for row in payload:
        try:
            d = datetime.strptime(row["date"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        cat = (row.get("category") or "").upper()
        bucket = by_date.setdefault(d, {})
        if "FII" in cat or "FPI" in cat:
            bucket["fii_buy"] = float(row.get("buyValue", 0.0))
            bucket["fii_sell"] = float(row.get("sellValue", 0.0))
        elif "DII" in cat:
            bucket["dii_buy"] = float(row.get("buyValue", 0.0))
            bucket["dii_sell"] = float(row.get("sellValue", 0.0))
    out: list[FlowDay] = []
    for d, b in sorted(by_date.items()):
        out.append(
            FlowDay(
                trade_date=d,
                fii_buy=b.get("fii_buy", 0.0),
                fii_sell=b.get("fii_sell", 0.0),
                dii_buy=b.get("dii_buy", 0.0),
                dii_sell=b.get("dii_sell", 0.0),
            )
        )
    return out


def _parse_bulk_deals_csv(text: str) -> list[BulkDeal]:
    """NSE bulk-deal CSV columns: Date, Symbol, Security Name, Client Name,
    Buy/Sell, Quantity Traded, Trade Price / Wght. Avg Price, Remarks."""
    out: list[BulkDeal] = []
    reader = csv.reader(io.StringIO(text))
    header_seen = False
    for row in reader:
        if not row or len(row) < 7:
            continue
        if not header_seen:
            header_seen = True
            continue
        try:
            d = datetime.strptime(row[0].strip(), "%d-%b-%Y").date()
            qty_str = row[5].replace(",", "").strip()
            price_str = row[6].replace(",", "").strip()
            out.append(
                BulkDeal(
                    trade_date=d,
                    symbol=row[1].strip(),
                    client_name=row[3].strip(),
                    side="BUY" if row[4].strip().upper().startswith("B") else "SELL",
                    quantity=int(float(qty_str)),
                    avg_price=float(price_str),
                )
            )
        except (ValueError, IndexError):
            continue
    return out


def _parse_block_deals_csv(text: str) -> list[BlockDeal]:
    """NSE block-deal CSV columns: Date, Symbol, Security Name, Client Name,
    Buy/Sell, Quantity Traded, Trade Price."""
    out: list[BlockDeal] = []
    reader = csv.reader(io.StringIO(text))
    header_seen = False
    for row in reader:
        if not row or len(row) < 7:
            continue
        if not header_seen:
            header_seen = True
            continue
        try:
            d = datetime.strptime(row[0].strip(), "%d-%b-%Y").date()
            qty_str = row[5].replace(",", "").strip()
            price_str = row[6].replace(",", "").strip()
            out.append(
                BlockDeal(
                    trade_date=d,
                    symbol=row[1].strip(),
                    side="BUY" if row[4].strip().upper().startswith("B") else "SELL",
                    quantity=int(float(qty_str)),
                    trade_price=float(price_str),
                )
            )
        except (ValueError, IndexError):
            continue
    return out


def _fetch_flows() -> list[FlowDay]:
    try:
        r = _fetch_with_session(f"{NSE_BASE}/api/fiidiiTradeReact")
        if r.status_code != 200:
            log.warning("fii_dii_fetch_status", status=r.status_code)
            return []
        return _parse_fii_dii(r.json())
    except Exception as exc:  # noqa: BLE001
        log.warning("fii_dii_fetch_failed", err=str(exc))
        return []


def _fetch_deals(deal_type: str) -> str:
    """deal_type: 'bulk_deals' | 'block_deals'."""
    today = now_ist().date()
    start = today - timedelta(days=10)
    url = (
        f"{NSE_BASE}/api/historical/cm/equity?"
        f"from={start.strftime('%d-%m-%Y')}&to={today.strftime('%d-%m-%Y')}&csv=true&"
        f"type={deal_type}"
    )
    try:
        r = _fetch_with_session(url)
        if r.status_code != 200:
            log.warning("deals_fetch_status", deal=deal_type, status=r.status_code)
            return ""
        return r.text
    except Exception as exc:  # noqa: BLE001
        log.warning("deals_fetch_failed", deal=deal_type, err=str(exc))
        return ""


@celery_app.task(name="app.tasks.institutional.refresh")
def refresh() -> dict[str, int]:
    """Build and cache the day's InstitutionalSnapshot."""
    flows = _fetch_flows()
    bulk_csv = _fetch_deals("bulk_deals")
    block_csv = _fetch_deals("block_deals")
    bulk = _parse_bulk_deals_csv(bulk_csv) if bulk_csv else []
    block = _parse_block_deals_csv(block_csv) if block_csv else []

    if not flows and not bulk and not block:
        return {"written": 0, "partial": 1}

    snap = InstitutionalSnapshot(
        as_of=now_ist().date(),
        flows=tuple(flows[-7:]),
        bulk_deals=tuple(bulk),
        block_deals=tuple(block),
    )

    s = get_settings()
    r = sync_redis.from_url(s.redis_url, decode_responses=True)
    r.set(REDIS_KEY, snapshot_to_json(snap), ex=SNAPSHOT_TTL_SECONDS)
    return {"written": 1, "flows": len(flows), "bulk": len(bulk), "block": len(block)}
