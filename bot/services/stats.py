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

CONSTRUCTION_HINTS = {
    "present_simple": "факты и привычки — «I work», «she likes»",
    "present_continuous": "прямо сейчас или временно — «I am working»",
    "present_perfect": "прошлое важно сейчас — «I have seen it»",
    "present_perfect_continuous": "процесс от прошлого до сейчас — «I have been waiting»",
    "past_simple": "конкретный момент в прошлом — «I went yesterday»",
    "past_continuous": "процесс в прошлом — «I was sleeping when...»",
    "past_perfect": "до другого события в прошлом — «I had left before she came»",
    "past_perfect_continuous": "процесс до события в прошлом — «I had been waiting for hours»",
    "future_simple": "решение на месте, предсказание — «I will call you»",
    "future_continuous": "процесс в будущем — «I will be working tomorrow»",
    "future_perfect": "завершится до момента в будущем — «I will have finished by 5»",
    "future_perfect_continuous": "длительность до момента в будущем",
    "conditional_0": "всегда верный факт — «If you heat water, it boils»",
    "conditional_1": "реальная ситуация в будущем — «If I study, I will pass»",
    "conditional_2": "нереальное сейчас — «If I were rich, I would travel»",
    "conditional_3": "нереальное в прошлом — «If I had known, I would have called»",
    "passive_voice": "важно что, а не кто — «It was built in 1990»",
    "reported_speech": "пересказ чужих слов — «He said he was tired»",
    "gerund": "глагол как существительное — «I enjoy swimming»",
    "infinitive": "цель или намерение — «I want to learn»",
    "modal_verbs": "can/should/must/might — степень обязанности/возможности",
    "relative_clauses": "уточнение через which/who/that — «the man who called»",
}


async def get_grammar_map(session: AsyncSession, user_id: int) -> dict:
    """Build grammar usage map data with AI analysis. Returns structured dict."""
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

    active = sorted([u for u in used if u["days_since_last_use"] <= 30], key=lambda x: -x["times_used"])
    dormant = sorted([u for u in used if u["days_since_last_use"] > 30], key=lambda x: x["days_since_last_use"])

    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import GRAMMAR_MAP_SYSTEM
    payload = {"used": used, "never_used": never_used}
    gpt = await ask_groq(GRAMMAR_MAP_SYSTEM, json.dumps(payload))

    return {
        "active": active,
        "dormant": dormant,
        "never_used": never_used,
        "gpt": gpt or {},
    }


def format_grammar_page(data: dict, page: int) -> tuple[str, int]:
    """Format grammar map for a specific page. Returns (text, total_pages)."""
    active = data.get("active", [])
    dormant = data.get("dormant", [])
    never_used = data.get("never_used", [])
    gpt = data.get("gpt", {})

    PER_PAGE = 8
    pages = []

    # Page 0: AI insight + active constructions
    p0_lines = ["🗺 Карта грамматики\n"]
    level = gpt.get("level_estimate")
    if level:
        p0_lines.append(f"Оценка уровня: {level}\n")

    insight = gpt.get("insight")
    if insight:
        p0_lines.append(f"💡 {insight}\n")

    strength = gpt.get("strength")
    if strength:
        label = CONSTRUCTION_LABELS.get(strength, strength)
        p0_lines.append(f"💪 Сильная сторона: {label}")

    gap = gpt.get("gap")
    gap_reason = gpt.get("gap_reason")
    if gap:
        label = CONSTRUCTION_LABELS.get(gap, gap)
        p0_lines.append(f"🎯 Главный пробел: {label}")
        if gap_reason:
            p0_lines.append(f"   {gap_reason}")

    next_step = gpt.get("next_step")
    if next_step:
        p0_lines.append(f"\n✏️ Попробуй сегодня:\n{next_step}")

    pages.append("\n".join(p0_lines))

    # Page 1: Active constructions (all)
    if active:
        p1_lines = ["✅ Активно использую:\n"]
        for u in active:
            label = CONSTRUCTION_LABELS.get(u["construction"], u["construction"])
            p1_lines.append(f"  • {label} — {u['times_used']}×")
        if dormant:
            p1_lines.append("\n💤 Давно не использовал:")
            for u in dormant[:5]:
                label = CONSTRUCTION_LABELS.get(u["construction"], u["construction"])
                p1_lines.append(f"  • {label} ({u['days_since_last_use']} дн. назад)")
        pages.append("\n".join(p1_lines))

    # Pages 2+: Never used with hints (paginated)
    if never_used:
        chunks = [never_used[i:i+PER_PAGE] for i in range(0, len(never_used), PER_PAGE)]
        for chunk in chunks:
            lines = ["❌ Ни разу не использовал:\n"]
            for c in chunk:
                name = CONSTRUCTION_LABELS.get(c, c)
                hint = CONSTRUCTION_HINTS.get(c, "")
                lines.append(f"  • {name}")
                if hint:
                    lines.append(f"    ↳ {hint}")
            pages.append("\n".join(lines))

    total = len(pages)
    page = max(0, min(page, total - 1))
    return pages[page], total


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
