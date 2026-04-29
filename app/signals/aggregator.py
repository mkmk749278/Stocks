from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import timedelta

from app.config import get_settings
from app.signals.base import AggregatedSignal, LayerSignal, Vote
from app.signals.registry import LAYER_WEIGHTS


@dataclass(slots=True)
class _SymbolWindow:
    """Rolling time-window of recent layer signals for one symbol."""

    items: deque[LayerSignal] = field(default_factory=deque)


class SignalAggregator:
    """Combines per-layer signals into a high-conviction AggregatedSignal.

    Rules (per AXIOM spec):
      - Fire only when >= settings.signal_min_layers agree on the same side
        within a `signal_window_seconds` window for the same symbol.
      - Confidence = weighted average of agreeing layers' scores using
        LAYER_WEIGHTS.
      - After a fire, the contributing entries are evicted to prevent re-firing
        on the same evidence.
    """

    def __init__(
        self,
        min_layers: int | None = None,
        window_seconds: int | None = None,
    ) -> None:
        s = get_settings()
        self.min_layers = min_layers if min_layers is not None else s.signal_min_layers
        self.window = timedelta(
            seconds=window_seconds if window_seconds is not None else s.signal_window_seconds
        )
        self._by_symbol: dict[str, _SymbolWindow] = defaultdict(_SymbolWindow)

    def ingest(self, sig: LayerSignal) -> AggregatedSignal | None:
        if sig.vote is Vote.NONE:
            return None
        win = self._by_symbol[sig.symbol]
        # evict expired
        cutoff = sig.ts_ist - self.window
        while win.items and win.items[0].ts_ist < cutoff:
            win.items.popleft()
        # replace any prior signal from the same layer (keep latest only)
        win.items = deque(s for s in win.items if s.layer != sig.layer)
        win.items.append(sig)

        agreeing = [s for s in win.items if s.vote == sig.vote]
        if len(agreeing) < self.min_layers:
            return None

        weights = [LAYER_WEIGHTS.get(s.layer, 1.0) for s in agreeing]
        scores = [s.score for s in agreeing]
        total_w = sum(weights)
        confidence = sum(w * x for w, x in zip(weights, scores, strict=True)) / total_w
        confidence = max(0.0, min(100.0, confidence))

        breakdown = {
            s.layer: {"score": s.score, "features": s.features} for s in agreeing
        }
        regime = next(
            (s.features.get("regime") for s in agreeing if s.features.get("regime")),
            "UNKNOWN",
        )

        # evict so the same set cannot re-fire
        for s in agreeing:
            try:
                win.items.remove(s)
            except ValueError:
                pass

        return AggregatedSignal(
            symbol=sig.symbol,
            side=sig.vote,
            confidence=confidence,
            ts_ist=sig.ts_ist,
            layers_voted=len(agreeing),
            breakdown=breakdown,
            regime=regime,
        )
