from __future__ import annotations

from app.celery_app import celery_app
from app.logger import get_logger
from app.timeutil import _holiday_set, now_ist

log = get_logger(__name__)


@celery_app.task(name="app.tasks.housekeeping.prepare_market_open")
def prepare_market_open() -> dict[str, str]:
    log.info("prepare_market_open", at=now_ist().isoformat())
    return {"status": "ok", "ts_ist": now_ist().isoformat()}


@celery_app.task(name="app.tasks.housekeeping.eod_rollup")
def eod_rollup() -> dict[str, str]:
    log.info("eod_rollup", at=now_ist().isoformat())
    return {"status": "ok", "ts_ist": now_ist().isoformat()}


@celery_app.task(name="app.tasks.housekeeping.refresh_holiday_cache")
def refresh_holiday_cache() -> dict[str, int]:
    _holiday_set.cache_clear()
    return {"holidays": len(_holiday_set())}
