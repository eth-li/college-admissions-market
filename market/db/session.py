"""
session.py — Async SQLAlchemy engine + session factory.

Default: SQLite file (`market.db`) in the project root — zero setup for local dev.
Production: set DATABASE_URL to a Postgres connection string and install asyncpg:

    DATABASE_URL=postgresql+asyncpg://user:pass@localhost/admissions uvicorn ...

The rest of the codebase doesn't need to change — SQLAlchemy handles the dialect.
"""

import os

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from market.db.models import Base

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./market.db",
)

# SQLite needs check_same_thread=False when used with async; Postgres doesn't.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_async_engine(
    DATABASE_URL,
    echo=False,          # flip to True to log every SQL statement (useful for debugging)
    future=True,
    connect_args=_connect_args,
)

# Session factory — creates one AsyncSession per request via get_db()
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep ORM objects usable after commit (important for FastAPI responses)
)


async def create_tables() -> None:
    """
    Create all tables defined in models.py if they don't exist.
    Idempotent — safe to call on every application startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """
    FastAPI dependency: yields a fresh AsyncSession for the current request,
    then closes it afterwards regardless of success or error.

    Usage in a route:
        async def my_route(db: AsyncSession = Depends(get_db)): ...
    """
    async with AsyncSessionLocal() as session:
        yield session
