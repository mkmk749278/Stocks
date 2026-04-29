from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "production"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    sentry_dsn: str | None = None

    database_url: str
    redis_url: str = "redis://127.0.0.1:6379/0"

    jwt_secret: str
    aes_master_key: str

    kite_api_key: str | None = None
    kite_api_secret: str | None = None
    kite_access_token: str | None = None

    telegram_bot_token: str | None = None
    telegram_channel_id: str | None = None

    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None

    signal_min_layers: int = Field(default=3, ge=1, le=9)
    signal_window_seconds: int = Field(default=60, ge=5, le=600)
    india_vix_hard_cap: float = 25.0
    daily_loss_cap_pct: float = 3.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
