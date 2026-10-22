"""Database engine, session factory and portable column types.

The application targets PostgreSQL 16 in production but the test-suite runs
against SQLite (aiosqlite) for hermetic, dependency free tests.  To make the
same declarative models work on both backends we expose small type aliases
that ``with_variant`` the PostgreSQL specific types to portable equivalents.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import JSON, String, Uuid
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings, get_settings

# --------------------------------------------------------------------------- #
# Portable column types
# --------------------------------------------------------------------------- #

#: JSON stored as native ``JSONB`` on PostgreSQL and ``TEXT`` JSON elsewhere.
JSONBType = JSONB().with_variant(JSON(), "sqlite")

#: PostgreSQL ``INET`` type with a ``VARCHAR(45)`` fallback for SQLite.
INETType = INET().with_variant(String(45), "sqlite")

#: UUID primary key type (native ``uuid`` on PG, ``CHAR(32)`` on SQLite).
UUIDType = Uuid(as_uuid=True)


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""

    type_annotation_map = {
        dict[str, Any]: JSONBType,
    }


def generate_uuid() -> uuid.UUID:
    """Return a new random UUID v4 (used as a column default)."""
    return uuid.uuid4()


# --------------------------------------------------------------------------- #
# Engine / session management
# --------------------------------------------------------------------------- #
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _engine_kwargs(settings: Settings) -> dict[str, Any]:
    """Build engine kwargs appropriate for the configured backend."""
    kwargs: dict[str, Any] = {
        "echo": settings.db_echo,
        "future": True,
        "pool_pre_ping": True,
    }
    if not settings.is_sqlite:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
    return kwargs


def create_engine(url: str | None = None, **overrides: Any) -> AsyncEngine:
    """Create a new async engine.

    Args:
        url: Optional explicit database URL (defaults to settings).
        **overrides: Additional keyword arguments merged into engine kwargs.

    Returns:
        A configured :class:`~sqlalchemy.ext.asyncio.AsyncEngine`.
    """
    settings = get_settings()
    kwargs = _engine_kwargs(settings)
    kwargs.update(overrides)
    return create_async_engine(url or settings.database_url, **kwargs)


def get_engine() -> AsyncEngine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an :class:`AsyncSession`.

    The session is rolled back and closed automatically.  Callers are
    responsible for committing.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the global engine (used on application shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
