from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import LEVELS, XP_NO_ERROR, XP_COMPLEX_NO_ERROR, XP_ERROR, XP_NEW_WORD
from bot.db.models import User, XpLog, Achievement

logger = logging.getLogger(__name__)

ACHIEVEMENT_DEFS = {
    "on_fire": ("🔥 On Fire", "100 сообщений без ошибок подряд"),
    "grammar_nerd": ("🎓 Grammar Nerd", "Использовал все 12 времён"),
    "vocab_beast": ("📚 Vocabulary Beast", "500 слов в словаре"),
    "speed_learner": ("⚡ Speed Learner", "0 ошибок за день (50+ сообщений)"),
    "perfect_week": ("🏆 Perfect Week", "Неделя с <2% ошибок"),
    "social_butterfly": ("🗣 Social Butterfly", "Английский в 10+ чатах"),
    "actor": ("🎭 Actor", "Пройти все сценарии roleplay"),
}


async def add_xp(session: AsyncSession, user_id: int, amount: int, reason: str) -> tuple[int, str | None]:
    """Add XP and return (new_xp, new_level_name_or_none)."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return 0, None

    old_level = user.level
    user.xp = max(0, user.xp + amount)

    # Determine level
    new_level = "newbie"
    for key, emoji, threshold in reversed(LEVELS):
        if user.xp >= threshold:
            new_level = key
            break
    user.level = new_level

    # Log XP
    session.add(XpLog(user_id=user_id, amount=amount, reason=reason))
    await session.commit()

    level_up = new_level if new_level != old_level else None
    return user.xp, level_up


async def update_streak(session: AsyncSession, user_id: int):
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return

    today = date.today()
    if user.last_active_date == today:
        return

    if user.last_active_date and (today - user.last_active_date).days == 1:
        user.streak += 1
    elif user.last_active_date != today:
        user.streak = 1

    user.last_active_date = today
    await session.commit()


async def grant_achievement(session: AsyncSession, user_id: int, key: str) -> str | None:
    existing = await session.execute(
        select(Achievement).where(
            Achievement.user_id == user_id,
            Achievement.achievement_key == key,
        )
    )
    if existing.scalar_one_or_none():
        return None

    session.add(Achievement(user_id=user_id, achievement_key=key))
    await session.commit()

    if key in ACHIEVEMENT_DEFS:
        emoji_name, desc = ACHIEVEMENT_DEFS[key]
        return f"🏆 Новое достижение!\n{emoji_name}\n{desc}"
    return None


def get_level_info(xp: int) -> tuple[str, str, int, int]:
    """Return (level_key, emoji, current_threshold, next_threshold)."""
    current = LEVELS[0]
    next_lvl = LEVELS[1] if len(LEVELS) > 1 else None

    for i, (key, emoji, threshold) in enumerate(LEVELS):
        if xp >= threshold:
            current = (key, emoji, threshold)
            next_lvl = LEVELS[i + 1] if i + 1 < len(LEVELS) else None

    next_threshold = next_lvl[2] if next_lvl else current[2]
    return current[0], current[1], current[2], next_threshold
