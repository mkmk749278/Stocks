from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.config import get_settings
from app.feed.base import TickFeed, infer_side
from app.logger import get_logger
from app.schemas.tick import TickEvent
from app.timeutil import IST, now_ist

log = get_logger(__name__)


class KiteWSFeed(TickFeed):
    """Zerodha Kite WebSocket feed.

    Reconnects with exponential backoff. Pushes TickEvents into an internal
    asyncio.Queue that consumers iterate via `stream()`.
    """

    def __init__(
        self,
        kite_tokens: list[int],
        token_to_symbol: dict[int, str],
        max_queue: int = 50_000,
    ) -> None:
        self._tokens = kite_tokens
        self._symbol_for = token_to_symbol
        self._queue: asyncio.Queue[TickEvent] = asyncio.Queue(maxsize=max_queue)
        self._closed = False
        self._kws: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _build_kws(self) -> Any:
        from kiteconnect import KiteTicker

        s = get_settings()
        if not (s.kite_api_key and s.kite_access_token):
            raise RuntimeError("KITE_API_KEY and KITE_ACCESS_TOKEN must be set")
        kws = KiteTicker(s.kite_api_key, s.kite_access_token)

        def on_connect(ws: Any, _resp: Any) -> None:
            ws.subscribe(self._tokens)
            ws.set_mode(ws.MODE_FULL, self._tokens)
            log.info("kite_ws_connected", tokens=len(self._tokens))

        def on_ticks(_ws: Any, ticks: list[dict[str, Any]]) -> None:
            if self._loop is None:
                return
            for t in ticks:
                ev = self._tick_to_event(t)
                if ev is None:
                    continue
                # cross-thread enqueue
                asyncio.run_coroutine_threadsafe(self._safe_put(ev), self._loop)

        def on_close(_ws: Any, code: int, reason: str) -> None:
            log.warning("kite_ws_closed", code=code, reason=reason)

        def on_error(_ws: Any, code: int, reason: str) -> None:
            log.error("kite_ws_error", code=code, reason=reason)

        kws.on_connect = on_connect
        kws.on_ticks = on_ticks
        kws.on_close = on_close
        kws.on_error = on_error
        return kws

    def _tick_to_event(self, t: dict[str, Any]) -> TickEvent | None:
        token = t.get("instrument_token")
        if token is None:
            return None
        sym = self._symbol_for.get(int(token))
        if sym is None:
            return None
        ts = t.get("exchange_timestamp") or t.get("last_trade_time")
        if ts is None:
            ts_ist = now_ist()
        elif ts.tzinfo is None:
            ts_ist = IST.localize(ts)
        else:
            ts_ist = ts.astimezone(IST)
        depth = t.get("depth") or {}
        bids = depth.get("buy") or []
        asks = depth.get("sell") or []
        bid = bids[0]["price"] if bids else None
        ask = asks[0]["price"] if asks else None
        bid_qty = bids[0]["quantity"] if bids else None
        ask_qty = asks[0]["quantity"] if asks else None
        price = float(t.get("last_price", 0.0))
        qty = int(t.get("last_traded_quantity", 0))
        return TickEvent(
            symbol=sym,
            kite_token=int(token),
            ts_ist=ts_ist,
            price=price,
            qty=qty,
            side=infer_side(price, bid, ask),
            bid=bid,
            ask=ask,
            bid_qty=bid_qty,
            ask_qty=ask_qty,
        )

    async def _safe_put(self, ev: TickEvent) -> None:
        try:
            self._queue.put_nowait(ev)
        except asyncio.QueueFull:
            log.warning("kite_ws_queue_full_dropping_tick", symbol=ev.symbol)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._kws = self._build_kws()
        # KiteTicker spawns its own thread; connect() returns immediately when threaded=True
        self._kws.connect(threaded=True, disable_ssl_verification=False)

    async def stream(self) -> AsyncIterator[TickEvent]:
        while not self._closed:
            try:
                ev = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                yield ev
            except asyncio.TimeoutError:
                continue

    async def close(self) -> None:
        self._closed = True
        if self._kws is not None:
            try:
                self._kws.close()
            except Exception:  # noqa: BLE001
                pass
