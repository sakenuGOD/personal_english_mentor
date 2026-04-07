from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import DATABASE_URL
from bot.db.models import Base

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_NEW_COLUMNS = [
    "ALTER TABLE users ADD COLUMN phrase_last_sent DATE",
    "ALTER TABLE users ADD COLUMN weekly_last_sent DATE",
    "ALTER TABLE users ADD COLUMN vocab_reminded_at DATETIME",
    "ALTER TABLE users ADD COLUMN api_balance_initial VARCHAR(50)",
    "ALTER TABLE users ADD COLUMN api_balance_set_at DATETIME",
]


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add new columns to existing DBs (SQLite ignores if column exists)
        for stmt in _NEW_COLUMNS:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
