from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.signals.base import Layer


# Layer weights (sum need not equal 1; aggregator normalizes).
# Source of truth — every aggregator vote uses these weights.
LAYER_WEIGHTS: dict[str, float] = {
    "ORDER_FLOW": 1.20,
    "VOLUME_PROFILE": 1.05,
    "OPTIONS_FLOW": 1.30,
    "INSTITUTIONAL": 1.15,
    "ML_MODELS": 1.40,
    "STAT_ARB": 0.90,
    "NLP_SENTIMENT": 0.75,
    "EVENT_DRIVEN": 1.00,
    "MACRO_INDIA": 0.80,
}


def _redis_options_loader():
    """Return a sync callable (underlying: str) -> OptionsSnapshot | None.

    Lazily imported so unit tests don't require a live Redis. Used by Celery
    workers to pull option-chain snapshots cached by the beat task.
    """
    import redis as sync_redis

    from app.config import get_settings
    from app.options_chain_io import REDIS_KEY_FMT, snapshot_from_json

    r = sync_redis.from_url(get_settings().redis_url, decode_responses=True)

    def _load(underlying: str):
        blob = r.get(REDIS_KEY_FMT.format(underlying=underlying))
        if blob is None:
            return None
        return snapshot_from_json(blob)

    return _load


def build_layers() -> list["Layer"]:
    """Instantiate every layer. Stub layers raise NotImplementedError on use."""
    from app.signals.layers.l1_order_flow import OrderFlowLayer
    from app.signals.layers.l2_volume_profile import VolumeProfileLayer
    from app.signals.layers.l3_options_flow import OptionsFlowLayer
    from app.signals.layers.l4_institutional import InstitutionalLayer
    from app.signals.layers.l5_ml_models import MLModelsLayer
    from app.signals.layers.l6_stat_arb import StatArbLayer
    from app.signals.layers.l7_nlp_sentiment import NLPSentimentLayer
    from app.signals.layers.l8_event_driven import EventDrivenLayer
    from app.signals.layers.l9_macro_india import MacroIndiaLayer

    try:
        options_loader = _redis_options_loader()
    except Exception:  # noqa: BLE001 — dev/test env without Redis
        options_loader = None

    return [
        OrderFlowLayer(),
        VolumeProfileLayer(),
        OptionsFlowLayer(redis_loader=options_loader),
        InstitutionalLayer(),
        MLModelsLayer(),
        StatArbLayer(),
        NLPSentimentLayer(),
        EventDrivenLayer(),
        MacroIndiaLayer(),
    ]
