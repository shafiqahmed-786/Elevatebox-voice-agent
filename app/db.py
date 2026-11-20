"""
Database session management.

Defaults to a local SQLite file so `uvicorn app.main:app` works with zero
setup. Set DATABASE_URL to a real Postgres DSN for anything beyond local
dev -- the assignment explicitly prefers Postgres for production, and
nothing else in the code assumes SQLite (SQLAlchemy's dialect differences
are the only thing that could bite, and none of the queries in this
codebase use anything Postgres/SQLite disagree on).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.db_models import Base

_settings = get_settings()

# postgresql+asyncpg://... in production; sqlite+aiosqlite:///... locally.
engine = create_async_engine(_settings.database_url, echo=False, future=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create tables if they don't exist. Fine for this project's scope
    (single-developer take-home, not a system with migration history to
    protect); a real production deployment would use Alembic instead."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session
