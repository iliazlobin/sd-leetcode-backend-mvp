from collections.abc import AsyncGenerator

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None
_redis_client = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            poolclass=NullPool,
            echo=settings.debug,
        )
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


def _get_redis():
    """Get or create a Redis client. Returns None if Redis is unavailable."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
        except Exception:
            return None
    return _redis_client


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()
