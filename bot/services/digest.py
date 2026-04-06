from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Error, Message, User, Vocabulary

logger = logging.getLogger(__name__)


async def generate_daily_digest(session: AsyncSession, user_id: int) -> str | None:
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Messages today
    total_result = await session.execute(
        select(func.count(Message.id)).where(
            Message.user_id == user_id,
            Message.created_at >= today_start,
        )
    )
    total = total_result.scalar() or 0

    if total == 0:
        return None

    # Errors today
    error_result = await session.execute(
        select(func.count(Message.id)).where(
            Message.user_id == user_id,
            Message.has_errors == True,
            Message.created_at >= today_start,
        )
    )
    errors = error_result.scalar() or 0
    rate = round(errors / total * 100, 1) if total > 0 else 0

    # User streak
    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    streak = user.streak if user else 0

    # Most frequent error today
    freq_error = await session.execute(
        select(Error.original_text, Error.corrected_text, Error.short_explanation, func.count(Error.id).label("cnt"))
        .where(Error.user_id == user_id, Error.created_at >= today_start)
        .group_by(Error.original_text, Error.corrected_text, Error.short_explanation)
        .order_by(func.count(Error.id).desc())
        .limit(1)
    )
    freq = freq_error.first()

    lines = [
        "📊 Дневной отчёт:\n",
        f"💬 Сообщений: {total}",
        f"❌ Ошибок: {errors} ({rate}%)",
        f"🔥 Streak: {streak} дней",
    ]

    if freq:
        orig, corr, expl, cnt = freq
        lines.append(f"\n🔁 Частая ошибка: \"{orig}\" (×{cnt})")
        lines.append(f"→ {corr} ({expl})")

    return "\n".join(lines)
