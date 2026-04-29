from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.signal import Signal as SignalRow
from app.models.signal import SignalSide
from app.redis_client import get_redis
from app.signals.base import AggregatedSignal, Vote

log = get_logger(__name__)

REDIS_PUBSUB_CHANNEL = "axiom:signals"


def format_telegram(sig: AggregatedSignal, levels: dict[str, float]) -> str:
    side_icon = "🟢 BUY" if sig.side is Vote.BUY else "🔴 SELL"
    layers_chips = " ".join(f"{k} ✅" for k in sig.breakdown.keys())
    return (
        f"{side_icon} — {sig.symbol}\n"
        f"📍 Entry: ₹{levels['entry_low']:.2f}–₹{levels['entry_high']:.2f}\n"
        f"🎯 T1: ₹{levels['target1']:.2f}"
        + (f" | 🎯 T2: ₹{levels['target2']:.2f}" if levels.get("target2") else "")
        + f" | 🛑 SL: ₹{levels['stop_loss']:.2f}\n"
        f"⚖️ R:R 1:{levels['risk_reward']:.2f} | ⏱️ {levels.get('timeframe', '5m')} "
        f"| 🧠 {sig.confidence:.1f}% | 📊 {sig.regime}\n"
        f"🔬 Layers: [{layers_chips}]"
    )


async def publish(
    session: AsyncSession,
    sig: AggregatedSignal,
    levels: dict[str, float],
    segment: str,
    timeframe: str = "5m",
) -> SignalRow:
    """Persist to PG, fan out via Redis pub/sub. Telegram delivery is a downstream subscriber."""
    row = SignalRow(
        symbol=sig.symbol,
        segment=segment,
        side=SignalSide.BUY if sig.side is Vote.BUY else SignalSide.SELL,
        entry_low=levels["entry_low"],
        entry_high=levels["entry_high"],
        target1=levels["target1"],
        target2=levels.get("target2"),
        stop_loss=levels["stop_loss"],
        risk_reward=levels["risk_reward"],
        timeframe=timeframe,
        confidence=sig.confidence,
        regime=sig.regime,
        layers_voted=sig.layers_voted,
        layer_breakdown=sig.breakdown,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    payload: dict[str, Any] = {
        "id": row.id,
        "symbol": row.symbol,
        "side": row.side.value,
        "confidence": row.confidence,
        "regime": row.regime,
        "fired_at": row.fired_at.isoformat(),
        "telegram_text": format_telegram(sig, levels),
    }
    try:
        await get_redis().publish(REDIS_PUBSUB_CHANNEL, json.dumps(payload))
    except Exception as exc:  # noqa: BLE001
        log.warning("redis_publish_failed", err=str(exc), signal_id=row.id)
    log.info("signal_fired", id=row.id, symbol=row.symbol, side=row.side.value)
    return row
