"""
Script to drop and rebuild all database tables.
WARNING: This will delete all data in the database!

Usage:
    python scripts/rebuild_db.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import from project
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import get_engine, Base
from db import models  # Import models to register them with Base


async def drop_all_tables():
    """Drop all tables from the database."""
    print("Dropping all tables...")
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("✓ All tables dropped")


async def create_all_tables():
    """Create all tables in the database."""
    print("Creating all tables...")
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ All tables created")


async def rebuild_database():
    """Drop and recreate all database tables."""
    print("\n" + "=" * 60)
    print("DATABASE REBUILD")
    print("=" * 60)
    print("WARNING: This will DELETE ALL DATA in the database!")
    print("=" * 60 + "\n")

    # Prompt for confirmation
    response = input("Are you sure you want to continue? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Rebuild cancelled.")
        return

    try:
        await drop_all_tables()
        await create_all_tables()

        print("\n" + "=" * 60)
        print("✓ Database rebuild completed successfully!")
        print("=" * 60)
        print("\nTables created:")
        print("  - users")
        print("  - follows")
        print("  - posts")
        print("  - check_ins")
        print("  - refresh_tokens")
        print("  - likes")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n✗ Error during rebuild: {e}")
        raise
    finally:
        # Close the engine
        engine = get_engine()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(rebuild_database())