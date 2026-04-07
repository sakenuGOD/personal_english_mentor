from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Error, Message, User, Vocabulary, XpLog

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


async def generate_weekly_insights(session: AsyncSession, user_id: int) -> str | None:
    now = datetime.utcnow()
    week_start = now - timedelta(days=7)
    prev_week_start = now - timedelta(days=14)

    # This week messages
    this_msgs = await session.execute(
        select(func.count(Message.id)).where(
            Message.user_id == user_id, Message.created_at >= week_start
        )
    )
    this_total = this_msgs.scalar() or 0
    if this_total == 0:
        return None

    this_errs = await session.execute(
        select(func.count(Message.id)).where(
            Message.user_id == user_id,
            Message.has_errors == True,
            Message.created_at >= week_start,
        )
    )
    this_err_count = this_errs.scalar() or 0

    # Previous week messages
    prev_msgs = await session.execute(
        select(func.count(Message.id)).where(
            Message.user_id == user_id,
            Message.created_at >= prev_week_start,
            Message.created_at < week_start,
        )
    )
    prev_total = prev_msgs.scalar() or 0

    prev_errs = await session.execute(
        select(func.count(Message.id)).where(
            Message.user_id == user_id,
            Message.has_errors == True,
            Message.created_at >= prev_week_start,
            Message.created_at < week_start,
        )
    )
    prev_err_count = prev_errs.scalar() or 0

    # Error rate change
    this_rate = (this_err_count / this_total * 100) if this_total else 0
    prev_rate = (prev_err_count / prev_total * 100) if prev_total else None

    # Top 3 error categories
    top_cats = await session.execute(
        select(Error.category, Error.original_text, Error.corrected_text, func.count(Error.id).label("cnt"))
        .where(Error.user_id == user_id, Error.created_at >= week_start)
        .group_by(Error.category)
        .order_by(func.count(Error.id).desc())
        .limit(3)
    )
    cats = top_cats.all()

    # XP this week
    xp_result = await session.execute(
        select(func.sum(XpLog.amount)).where(
            XpLog.user_id == user_id, XpLog.created_at >= week_start
        )
    )
    xp_earned = xp_result.scalar() or 0

    # Vocab added this week
    vocab_result = await session.execute(
        select(func.count(Vocabulary.id)).where(
            Vocabulary.user_id == user_id, Vocabulary.created_at >= week_start
        )
    )
    vocab_added = vocab_result.scalar() or 0

    # GPT for focus rule and motivation
    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import WEEKLY_INSIGHTS_SYSTEM
    payload = {
        "this_week": {"messages": this_total, "errors": this_err_count, "error_rate": round(this_rate, 1)},
        "prev_week": {"messages": prev_total, "errors": prev_err_count, "error_rate": round(prev_rate, 1) if prev_rate is not None else None},
        "top_categories": [{"category": c, "count": n} for c, _, _, n in cats],
        "xp_earned": xp_earned,
        "vocab_added": vocab_added,
    }
    gpt = await ask_groq(WEEKLY_INSIGHTS_SYSTEM, json.dumps(payload))

    # Build message
    sep = "=" * 30
    lines = [sep, "📊 Инсайты недели", ""]

    # Error trend
    if prev_rate is not None and prev_rate > 0:
        delta = this_rate - prev_rate
        arrow = "↓" if delta < -1 else ("↑" if delta > 1 else "→")
        sign = "+" if delta > 0 else ""
        lines.append(f"❌ Ошибки: {round(prev_rate, 1)}% → {round(this_rate, 1)}% {arrow} ({sign}{round(delta, 1)}%)")
    else:
        lines.append(f"❌ Ошибки: {round(this_rate, 1)}% за неделю")

    lines.append(f"💬 Сообщений: {this_total}")
    lines.append(f"⚡ XP за неделю: +{xp_earned}")
    if vocab_added:
        lines.append(f"📚 Новых слов: {vocab_added}")

    if cats:
        lines.append("")
        lines.append("Топ ошибок:")
        from bot.services.stats import CATEGORY_NAMES
        for i, (cat, orig, corr, cnt) in enumerate(cats, 1):
            cat_name = CATEGORY_NAMES.get(cat, cat)
            example = f' ("{orig}" → "{corr}")' if orig and corr else ""
            lines.append(f"  {i}. {cat_name} — {cnt} раз{example}")

    if gpt:
        focus = gpt.get("focus_rule")
        motivation = gpt.get("motivation")
        if focus:
            lines.append("")
            lines.append(f"🎯 Правило недели:\n{focus}")
        if motivation:
            lines.append("")
            lines.append(f"💬 {motivation}")

    lines.append(sep)
    return "\n".join(lines)
