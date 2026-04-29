from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_engine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    future=True,
)
_SessionLocal = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


def get_engine() -> Any:
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _SessionLocal() as session:
        yield session


async def session_scope() -> AsyncSession:
    return _SessionLocal()
