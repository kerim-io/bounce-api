from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from typing import AsyncGenerator
from core.config import settings

DATABASE_URL = settings.DATABASE_URL

engine = None
async_session_maker = None
Base = declarative_base()


def get_engine():
    global engine
    if engine is None:
        engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            pool_size=20,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=3600
        )
    return engine


def get_session_maker():
    global async_session_maker
    if async_session_maker is None:
        async_session_maker = sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return async_session_maker


async def create_db_and_tables():
    from . import models
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Run migrations for new columns
    await run_migrations()


async def run_migrations():
    """Run any pending column additions"""
    from sqlalchemy import text

    migrations = [
        # Users table
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS instagram_handle VARCHAR(30)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS instagram_profile_pic TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS linkedin_handle VARCHAR(100)",
        # Posts table
        "ALTER TABLE posts ADD COLUMN IF NOT EXISTS venue_name VARCHAR(255)",
        "ALTER TABLE posts ADD COLUMN IF NOT EXISTS venue_id VARCHAR(255)",
    ]

    engine = get_engine()
    async with engine.begin() as conn:
        for migration in migrations:
            try:
                await conn.execute(text(migration))
            except Exception as e:
                # Column might already exist or other non-critical error
                pass


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    session_maker = get_session_maker()
    async with session_maker() as session:
        yield session


def create_async_session() -> AsyncSession:
    """Create a new AsyncSession for WebSocket. Caller must close it."""
    session_maker = get_session_maker()
    return session_maker()
