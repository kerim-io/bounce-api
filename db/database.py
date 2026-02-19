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
            pool_size=50,
            max_overflow=30,
            pool_timeout=30,
            pool_recycle=3600,
            pool_pre_ping=True
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
        # Profile pictures (base64 stored in DB)
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture_1 TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture_2 TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture_3 TEXT",
        # Places table
        "ALTER TABLE places ADD COLUMN IF NOT EXISTS bounce_count INTEGER DEFAULT 0",
        "ALTER TABLE places ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE",
        # Bounces table
        "ALTER TABLE bounces ADD COLUMN IF NOT EXISTS place_id INTEGER REFERENCES places(id) ON DELETE SET NULL",
        # Check-ins table
        "ALTER TABLE check_ins ADD COLUMN IF NOT EXISTS place_id VARCHAR(255)",
        "ALTER TABLE check_ins ADD COLUMN IF NOT EXISTS places_fk_id INTEGER REFERENCES places(id) ON DELETE SET NULL",
        "ALTER TABLE check_ins ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        "ALTER TABLE check_ins ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
        # Indexes
        "CREATE INDEX IF NOT EXISTS ix_bounces_place_id ON bounces(place_id)",
        "CREATE INDEX IF NOT EXISTS idx_checkins_place_id ON check_ins(place_id)",
        "CREATE INDEX IF NOT EXISTS idx_checkins_places_fk ON check_ins(places_fk_id)",
        "CREATE INDEX IF NOT EXISTS idx_checkins_last_seen ON check_ins(last_seen_at)",
        "CREATE INDEX IF NOT EXISTS idx_checkins_active ON check_ins(is_active) WHERE is_active = true",
        # Follows table - close friend feature
        "ALTER TABLE follows ADD COLUMN IF NOT EXISTS is_close_friend BOOLEAN DEFAULT FALSE",
        # Performance indexes for high-traffic queries
        "CREATE INDEX IF NOT EXISTS idx_follows_follower_following ON follows(follower_id, following_id)",
        "CREATE INDEX IF NOT EXISTS idx_device_tokens_user_active ON device_tokens(user_id, is_active) WHERE is_active = true",
        # Admin dashboard
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE",
        "CREATE INDEX IF NOT EXISTS idx_users_is_admin ON users(is_admin) WHERE is_admin = TRUE",
        # Bounce share link
        "ALTER TABLE bounces ADD COLUMN IF NOT EXISTS share_token VARCHAR(64) UNIQUE",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bounces_share_token ON bounces(share_token)",
        # Venue feed messages
        "CREATE INDEX IF NOT EXISTS idx_venue_feed_place_id ON venue_feed_messages(place_id)",
        "CREATE INDEX IF NOT EXISTS idx_venue_feed_place_id_desc ON venue_feed_messages(place_id, id DESC)",
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
