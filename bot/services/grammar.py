from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Error, Message, User
from bot.services.groq_client import ask_groq
from bot.utils.prompts import AUTOCORRECT_SYSTEM, AUTOCORRECT_USER, AUTOCORRECT_USER_CTX, GRAMMAR_DETECT_SYSTEM, GRAMMAR_DETECT_USER

logger = logging.getLogger(__name__)


async def check_grammar(text: str, mode: str = "balanced", api_key: str | None = None, context: str = "") -> dict | None:
    if context:
        user_msg = AUTOCORRECT_USER_CTX.format(mode=mode, text=text, context=context)
    else:
        user_msg = AUTOCORRECT_USER.format(mode=mode, text=text)
    return await ask_groq(AUTOCORRECT_SYSTEM, user_msg, api_key=api_key)


async def check_grammar_free(text: str, mode: str = "balanced") -> dict | None:
    """Check grammar using free APIs (Groq → Gemini fallback). Returns None if both exhausted."""
    from bot.services.free_llm import ask_free_llm
    user_msg = AUTOCORRECT_USER.format(mode=mode, text=text)
    return await ask_free_llm(AUTOCORRECT_SYSTEM, user_msg)


async def detect_errors_free(text: str, mode: str = "balanced") -> dict | None:
    """Lightweight error detection via free API. Returns {has_errors} or None."""
    from bot.services.free_llm import ask_free_llm
    user_msg = GRAMMAR_DETECT_USER.format(mode=mode, text=text)
    result = await ask_free_llm(GRAMMAR_DETECT_SYSTEM, user_msg)
    if result is None:
        return None
    # Normalize minimal keys: "e" → "has_errors", "c" → "categories"
    return {
        "has_errors": result.get("e", result.get("has_errors", False)),
        "categories": result.get("c", result.get("categories", [])),
    }



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


def format_detailed_correction(corrections: list[dict], chat_name: str = "") -> list[str]:
    """Format corrections into pages (list of strings). Each correction = 1 page."""
    sep = "━" * 24

    # Page 1: compact overview
    p1 = [sep]
    if chat_name:
        p1.append(f"Чат {chat_name}")

    full = corrections[0].get("full_sentence", "") if corrections else ""
    if full:
        p1.append(f'\n❌ {full}')

    corrected_full = corrections[0].get("corrected_full", "") if corrections else ""
    if corrected_full:
        p1.append(f'✅ {corrected_full}')

    if len(corrections) > 1:
        p1.append(f"\n{len(corrections)} ошибок — листай ▶️")
    p1.append(sep)

    pages = ["\n".join(p1)]

    # One page per correction — ALWAYS
    for i, c in enumerate(corrections):
        explanation = c.get("detailed_explanation", "")
        rule = c.get("rule_name", "")
        when = c.get("when_to_use", "")
        formula = c.get("formula", "")
        short = c.get("short_explanation", "")
        original = c.get("original", "")
        corrected = c.get("corrected", "")

        lines = [f"❌ {original}  →  ✅ {corrected}"]

        native_hears = c.get("native_hears", "")
        if native_hears:
            lines.append(f"\n👂 Носитель услышал: {native_hears}")

        if rule:
            lines.append(f"\n📐 {rule}")
        if formula:
            lines.append(f"✏️ {formula}")

        if explanation:
            lines.append(f"\n{explanation}")
        elif short:
            lines.append(f"\n{short}")

        if when:
            lines.append(f"\n⏰ {when}")

        pages.append("\n".join(lines))

    return pages
