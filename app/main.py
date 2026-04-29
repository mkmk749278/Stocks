from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import sentry_sdk
from fastapi import FastAPI
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app import __version__
from app.api import health, signals
from app.config import get_settings
from app.logger import configure_logging, get_logger
from app.redis_client import close_redis

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    configure_logging()
    settings = get_settings()
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[FastApiIntegration()],
            traces_sample_rate=0.1,
            environment=settings.app_env,
            release=f"axiom@{__version__}",
        )
    log.info("axiom_startup", env=settings.app_env, version=__version__)
    try:
        yield
    finally:
        await close_redis()
        log.info("axiom_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AXIOM Signal Engine",
        version=__version__,
        description="Indian stock market (NSE/BSE) signal engine.",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(signals.router, prefix="/api/v1")
    return app


app = create_app()
