from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.signals.base import AggregatedSignal
from app.timeutil import auto_trade_window_open


@dataclass(slots=True)
class RiskCheckResult:
    ok: bool
    reasons: list[str]


def pre_publish_checks(
    sig: AggregatedSignal,
    *,
    india_vix: float,
    daily_pnl_pct: float,
) -> RiskCheckResult:
    """Run hard gates before any signal is published or auto-traded.

    Returns ok=False with all failing reasons; caller drops or downgrades.
    """
    s = get_settings()
    reasons: list[str] = []

    if not auto_trade_window_open():
        reasons.append("outside_auto_trade_window_9_20_15_20_ist")
    if india_vix > s.india_vix_hard_cap:
        reasons.append(f"india_vix_{india_vix:.2f}_above_cap_{s.india_vix_hard_cap:.2f}")
    if daily_pnl_pct <= -s.daily_loss_cap_pct:
        reasons.append(
            f"daily_loss_cap_breached_{daily_pnl_pct:.2f}_le_-{s.daily_loss_cap_pct:.2f}"
        )
    if sig.confidence < 60.0:
        reasons.append(f"confidence_{sig.confidence:.1f}_below_60")

    return RiskCheckResult(ok=not reasons, reasons=reasons)
