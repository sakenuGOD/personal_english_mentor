from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Error, Message, User
from bot.services.groq_client import ask_groq
from bot.utils.prompts import AUTOCORRECT_SYSTEM, AUTOCORRECT_USER

logger = logging.getLogger(__name__)


async def check_grammar(text: str, mode: str = "balanced", api_key: str | None = None) -> dict | None:
    user_msg = AUTOCORRECT_USER.format(mode=mode, text=text)
    return await ask_groq(AUTOCORRECT_SYSTEM, user_msg, api_key=api_key)



async def save_error(
    session: AsyncSession,
    user_id: int,
    chat_id: int,
    correction: dict,
):
    error = Error(
        user_id=user_id,
        chat_id=chat_id,
        original_text=correction.get("original", ""),
        corrected_text=correction.get("corrected", ""),
        category=correction.get("category", "other"),
        rule_name=correction.get("rule_name", ""),
        short_explanation=correction.get("short_explanation", ""),
        detailed_explanation=correction.get("detailed_explanation", ""),
    )
    session.add(error)


async def save_message(
    session: AsyncSession,
    user_id: int,
    chat_id: int,
    has_errors: bool,
    error_count: int = 0,
):
    msg = Message(
        user_id=user_id,
        chat_id=chat_id,
        has_errors=has_errors,
        error_count=error_count,
    )
    session.add(msg)


def format_chat_correction(corrections: list[dict], corrected_full: str = "") -> str:
    if not corrections:
        return ""
    if corrected_full:
        return f"*{corrected_full}"
    parts = []
    for c in corrections[:3]:
        parts.append(f"{c.get('original', '')} → {c['corrected']}")
    return "*" + ", ".join(parts)


def format_detailed_correction(corrections: list[dict], chat_name: str = "") -> str:
    sep = "=" * 30
    lines = [sep]
    if chat_name:
        lines.append(f"Чат {chat_name}")

    # Original sentence
    full = corrections[0].get("full_sentence", "") if corrections else ""
    if full:
        lines.append(f'\n❌ {full}')

    # Corrected full sentence
    corrected_full = corrections[0].get("corrected_full", "") if corrections else ""
    if corrected_full:
        lines.append(f'✅ {corrected_full}')

    # Show each correction
    lines.append("")
    for c in corrections:
        original = c.get("original", "")
        corrected = c.get("corrected", "")
        lines.append(f"  • {original}  →  {corrected}")

    lines.append("")

    # Explanation
    lines.append(f"{'─' * 20}")
    lines.append("📖 Разбор")
    lines.append("")
    for c in corrections:
        explanation = c.get("detailed_explanation", "")
        if explanation:
            lines.append(explanation)
            lines.append("")

    # Rule & when to use
    rule = corrections[0].get("rule_name", "") if corrections else ""
    if rule:
        lines.append(f"{'─' * 20}")
        lines.append(f"📏 Правило: {rule}")
        lines.append("")

        when = corrections[0].get("when_to_use", "")
        if when:
            lines.append(f"⏰ Когда: {when}")
            lines.append("")

        formula = corrections[0].get("formula", "")
        if formula:
            lines.append(f"🔢 Формула: {formula}")
            lines.append("")

    lines.append(sep)
    return "\n".join(lines)
