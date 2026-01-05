"""Database connection management."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import get_settings

logger = logging.getLogger(__name__)

# Global engine and session factory
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def create_db_pool() -> None:
    """Initialize the database connection pool."""
    global _engine, _session_factory

    settings = get_settings()

    _engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    logger.info("Database connection pool created")

    # Auto-create tables on startup
    await init_db()


async def init_db() -> None:
    """Create database tables and run migrations for new columns."""
    from src.database.models import Base
    from sqlalchemy import text

    if _engine is None:
        raise RuntimeError("Database engine not initialized")

    async with _engine.begin() as conn:
        # Create tables if they don't exist
        await conn.run_sync(Base.metadata.create_all)

        # Add missing columns to existing tables (migrations)
        migrations = [
            # Users table migrations
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_setup_complete BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS household_id UUID",
            # Expenses table migrations
            "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS group_chat_id BIGINT",
        ]

        for migration in migrations:
            try:
                await conn.execute(text(migration))
            except Exception as e:
                # Column might already exist or other non-critical error
                logger.debug(f"Migration note: {e}")

        # Create indexes if they don't exist
        indexes = [
            "CREATE INDEX IF NOT EXISTS ix_expenses_group_chat_id ON expenses(group_chat_id)",
            "CREATE INDEX IF NOT EXISTS ix_expense_items_name_normalized ON expense_items(name_normalized)",
        ]

        for index_sql in indexes:
            try:
                await conn.execute(text(index_sql))
            except Exception as e:
                logger.debug(f"Index creation note: {e}")

    logger.info("Database tables and migrations completed")


async def close_db_pool() -> None:
    """Close the database connection pool."""
    global _engine, _session_factory

    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection pool closed")


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the session factory."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call create_db_pool() first.")
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get a database session as a context manager."""
    factory = get_session_factory()

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
