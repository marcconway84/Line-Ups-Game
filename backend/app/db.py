"""Database engine and session handling.

Defaults to a local SQLite file so the game runs with no infrastructure at all. Point
DATABASE_URL at Postgres to use the schema in ``db/schema.sql`` instead - sync-style
URLs are upgraded to their async driver automatically, so both of these work:

    DATABASE_URL=postgresql://user:pass@localhost:5432/lineups_db
    DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/lineups_db
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = REPO_ROOT / "lineups.db"

#: sync driver -> async driver, so a plain Postgres URL still works.
_ASYNC_DRIVERS = {
    "postgresql://": "postgresql+asyncpg://",
    "postgres://": "postgresql+asyncpg://",
    "sqlite://": "sqlite+aiosqlite://",
}


def resolve_database_url(raw: str | None = None) -> str:
    url = (raw if raw is not None else os.getenv("DATABASE_URL", "")).strip()
    if not url:
        return f"sqlite+aiosqlite:///{DEFAULT_SQLITE_PATH}"
    for prefix, replacement in _ASYNC_DRIVERS.items():
        if url.startswith(prefix):
            return replacement + url[len(prefix) :]
    return url


DATABASE_URL = resolve_database_url()

engine: AsyncEngine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_all() -> None:
    """Create any missing tables.

    Fine for SQLite and for getting started on Postgres. Once the schema starts changing
    in production, swap this for Alembic migrations generated from these models.
    """
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session per request."""
    async with AsyncSessionLocal() as session:
        yield session
