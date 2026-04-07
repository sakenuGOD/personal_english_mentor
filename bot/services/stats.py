from __future__ import annotations

import json
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


ALL_CONSTRUCTIONS = [
    "present_simple", "present_continuous", "present_perfect", "present_perfect_continuous",
    "past_simple", "past_continuous", "past_perfect", "past_perfect_continuous",
    "future_simple", "future_continuous", "future_perfect", "future_perfect_continuous",
    "conditional_0", "conditional_1", "conditional_2", "conditional_3",
    "passive_voice", "reported_speech", "gerund", "infinitive", "modal_verbs", "relative_clauses",
]

CONSTRUCTION_LABELS = {
    "present_simple": "Present Simple",
    "present_continuous": "Present Continuous",
    "present_perfect": "Present Perfect",
    "present_perfect_continuous": "Present Perfect Continuous",
    "past_simple": "Past Simple",
    "past_continuous": "Past Continuous",
    "past_perfect": "Past Perfect",
    "past_perfect_continuous": "Past Perfect Continuous",
    "future_simple": "Future Simple",
    "future_continuous": "Future Continuous",
    "future_perfect": "Future Perfect",
    "future_perfect_continuous": "Future Perfect Continuous",
    "conditional_0": "Conditional 0",
    "conditional_1": "Conditional 1",
    "conditional_2": "Conditional 2",
    "conditional_3": "Conditional 3",
    "passive_voice": "Passive Voice",
    "reported_speech": "Reported Speech",
    "gerund": "Gerund",
    "infinitive": "Infinitive",
    "modal_verbs": "Modal Verbs",
    "relative_clauses": "Relative Clauses",
}


async def get_grammar_map(session: AsyncSession, user_id: int) -> str:
    """Build grammar usage map with AI analysis."""
    now = datetime.utcnow()

    rows = await session.execute(
        select(GrammarUsage).where(GrammarUsage.user_id == user_id)
    )
    usages = {g.construction: g for g in rows.scalars().all()}

    used = []
    for c, g in usages.items():
        days_since = (now - g.last_used).days if g.last_used else 999
        used.append({"construction": c, "times_used": g.times_used, "days_since_last_use": days_since})

    never_used = [c for c in ALL_CONSTRUCTIONS if c not in usages]

    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import GRAMMAR_MAP_SYSTEM
    payload = {"used": used, "never_used": never_used}
    gpt = await ask_groq(GRAMMAR_MAP_SYSTEM, json.dumps(payload))

    # Build text output
    lines = ["🗺 Карта грамматики", ""]

    # Used constructions grouped
    if used:
        active = sorted(
            [u for u in used if u["days_since_last_use"] <= 30],
            key=lambda x: -x["times_used"]
        )
        dormant = [u for u in used if u["days_since_last_use"] > 30]

        if active:
            lines.append("✅ Активно использую:")
            for u in active[:8]:
                label = CONSTRUCTION_LABELS.get(u["construction"], u["construction"])
                lines.append(f"  • {label} — {u['times_used']}× ")

        if dormant:
            lines.append("")
            lines.append("💤 Давно не использовал:")
            for u in dormant[:5]:
                label = CONSTRUCTION_LABELS.get(u["construction"], u["construction"])
                lines.append(f"  • {label} ({u['days_since_last_use']} дн. назад)")

    if never_used:
        lines.append("")
        lines.append("❌ Никогда не использовал:")
        for c in never_used[:8]:
            lines.append(f"  • {CONSTRUCTION_LABELS.get(c, c)}")
        if len(never_used) > 8:
            lines.append(f"  ... и ещё {len(never_used) - 8}")

    if gpt:
        level = gpt.get("level_estimate")
        insight = gpt.get("insight")
        focus = gpt.get("focus")
        if level:
            lines.insert(1, f"Оценка уровня: {level}")
        if insight:
            lines.append("")
            lines.append(f"💡 {insight}")
        if focus:
            lines.append("")
            lines.append(f"🎯 Что практиковать дальше: {focus}")

    return "\n".join(lines)


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
