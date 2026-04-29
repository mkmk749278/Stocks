from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "axiom",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=[
        "app.tasks.signal_tasks",
        "app.tasks.housekeeping",
        "app.tasks.options_chain",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=5,
    task_default_max_retries=3,
)

celery_app.conf.beat_schedule = {
    # Mon-Fri 9:14 IST: prime feed + warm caches just before market open
    "prepare-market-open": {
        "task": "app.tasks.housekeeping.prepare_market_open",
        "schedule": crontab(hour=9, minute=14, day_of_week="mon-fri"),
    },
    # Mon-Fri 15:35 IST: roll up EOD aggregates
    "eod-rollup": {
        "task": "app.tasks.housekeeping.eod_rollup",
        "schedule": crontab(hour=15, minute=35, day_of_week="mon-fri"),
    },
    # Daily 23:30 IST: refresh holiday cache for tomorrow
    "refresh-holidays": {
        "task": "app.tasks.housekeeping.refresh_holiday_cache",
        "schedule": crontab(hour=23, minute=30),
    },
    # Every minute during market hours: pull NFO option chain into Redis cache
    "refresh-options-snapshots": {
        "task": "app.tasks.options_chain.refresh_options_snapshots",
        "schedule": crontab(minute="*", hour="9-15", day_of_week="mon-fri"),
    },
}
