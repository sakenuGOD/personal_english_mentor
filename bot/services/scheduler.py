from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

from sqlalchemy import select, update

from bot.db.database import async_session
from bot.db.models import User

logger = logging.getLogger(__name__)


async def scheduler_loop(bot):
    """Runs forever, fires scheduled tasks every 60 seconds."""
    logger.info("Scheduler started")
    while True:
        try:
            await asyncio.sleep(60)
            now = datetime.now(timezone.utc)
            await _check_phrase_of_day(bot, now)
            if now.weekday() == 6:  # Sunday
                await _check_weekly_insights(bot, now)
        except Exception as e:
            logger.error(f"Scheduler error: {e}")


async def _check_phrase_of_day(bot, now: datetime):
    """Send phrase of the day to users whose time has come."""
    today = date.today()
    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                User.notifications == True,
            )
        )
        users = result.scalars().all()

    for user in users:
        try:
            # Skip if already sent today
            if user.phrase_last_sent and user.phrase_last_sent >= today:
                continue

            # Check if current UTC hour matches digest_time hour (simple check)
            digest_hour = user.digest_time.hour if user.digest_time else 9
            if now.hour != digest_hour:
                continue

            # Generate and send phrase
            from bot.services.phrase_of_day import generate_phrase_of_day, format_phrase_message
            phrase = await generate_phrase_of_day(user.topic_pack or "general")
            if not phrase:
                continue

            text = format_phrase_message(phrase)
            await bot.send_message(chat_id=user.id, text=text)

            # Mark as sent
            async with async_session() as session:
                await session.execute(
                    update(User).where(User.id == user.id).values(phrase_last_sent=today)
                )
                await session.commit()

            logger.info(f"Sent phrase of day to user {user.id}")

        except Exception as e:
            logger.warning(f"Failed to send phrase to user {user.id}: {e}")


async def _check_weekly_insights(bot, now: datetime):
    """Send weekly insights every Sunday."""
    today = date.today()
    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                User.notifications == True,
            )
        )
        users = result.scalars().all()

    for user in users:
        try:
            if user.weekly_last_sent and user.weekly_last_sent >= today:
                continue

            # Only send at digest hour
            digest_hour = user.digest_time.hour if user.digest_time else 21
            if now.hour != digest_hour:
                continue

            from bot.services.digest import generate_weekly_insights
            async with async_session() as session:
                text = await generate_weekly_insights(session, user.id)

            if not text:
                continue

            await bot.send_message(chat_id=user.id, text=text)

            async with async_session() as session:
                await session.execute(
                    update(User).where(User.id == user.id).values(weekly_last_sent=today)
                )
                await session.commit()

            logger.info(f"Sent weekly insights to user {user.id}")

        except Exception as e:
            logger.warning(f"Failed to send weekly insights to user {user.id}: {e}")
