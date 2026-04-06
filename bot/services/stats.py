from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Error, Message, Vocabulary, GrammarUsage, Achievement, User

CATEGORY_NAMES = {
    "tenses": "Времена",
    "articles": "Артикли",
    "prepositions": "Предлоги",
    "word_order": "Порядок слов",
    "vocabulary": "Лексика",
    "spelling": "Орфография",
    "subject_verb_agreement": "Согласование",
    "conditionals": "Условные",
    "passive": "Пассивный залог",
    "verb_forms": "Формы глагола",
    "punctuation": "Пунктуация",
    "other": "Другое",
}


def get_category_name(cat: str) -> str:
    return CATEGORY_NAMES.get(cat, cat)


async def get_user_stats(session: AsyncSession, user_id: int) -> dict:
    # Total messages
    total_msgs = await session.execute(
        select(func.count(Message.id)).where(Message.user_id == user_id)
    )
    total = total_msgs.scalar() or 0

    # Messages with errors
    error_msgs = await session.execute(
        select(func.count(Message.id)).where(
            Message.user_id == user_id, Message.has_errors == True
        )
    )
    errors = error_msgs.scalar() or 0

    # Error rate
    error_rate = (errors / total * 100) if total > 0 else 0

    # Week ago stats
    week_ago = datetime.utcnow() - timedelta(days=7)
    week_total = await session.execute(
        select(func.count(Message.id)).where(
            Message.user_id == user_id, Message.created_at >= week_ago
        )
    )
    week_total_val = week_total.scalar() or 0

    week_errors = await session.execute(
        select(func.count(Message.id)).where(
            Message.user_id == user_id,
            Message.has_errors == True,
            Message.created_at >= week_ago,
        )
    )
    week_errors_val = week_errors.scalar() or 0
    week_rate = (week_errors_val / week_total_val * 100) if week_total_val > 0 else 0

    # Top error categories
    top_cats = await session.execute(
        select(Error.category, func.count(Error.id).label("cnt"))
        .where(Error.user_id == user_id)
        .group_by(Error.category)
        .order_by(func.count(Error.id).desc())
        .limit(5)
    )
    top_categories = [(row[0], row[1]) for row in top_cats.all()]

    # Total errors count
    total_errors = await session.execute(
        select(func.count(Error.id)).where(Error.user_id == user_id)
    )
    total_errors_val = total_errors.scalar() or 0

    # Vocab count
    vocab_count = await session.execute(
        select(func.count(Vocabulary.id)).where(Vocabulary.user_id == user_id)
    )
    vocab = vocab_count.scalar() or 0

    # User data
    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    return {
        "total_messages": total,
        "error_messages": errors,
        "error_rate": round(error_rate, 1),
        "week_rate": round(week_rate, 1),
        "top_categories": top_categories,
        "total_errors": total_errors_val,
        "vocab_count": vocab,
        "xp": user.xp if user else 0,
        "level": user.level if user else "newbie",
        "streak": user.streak if user else 0,
    }


def format_stats(stats: dict) -> str:
    from bot.config import LEVELS
    level_emoji = "🥉"
    for key, emoji, threshold in LEVELS:
        if key == stats["level"]:
            level_emoji = emoji
            break

    trend = "📈" if stats["week_rate"] < stats["error_rate"] else "📉"

    lines = [
        f"{level_emoji} {stats['level'].title()} • {stats['xp']} XP • 🔥 {stats['streak']} дн.",
        "",
        f"📨 Сообщений: {stats['total_messages']}",
        f"❌ Ошибки: {stats['error_rate']}% (неделя: {stats['week_rate']}% {trend})",
        f"📚 Слов в словаре: {stats['vocab_count']}",
    ]

    if stats["top_categories"]:
        lines.append("")
        lines.append("Слабые места:")
        for cat, cnt in stats["top_categories"][:3]:
            lines.append(f"  • {get_category_name(cat)} — {cnt}")

    return "\n".join(lines)
