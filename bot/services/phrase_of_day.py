from __future__ import annotations

import logging

from bot.services.groq_client import ask_groq
from bot.utils.prompts import PHRASE_OF_DAY_SYSTEM

logger = logging.getLogger(__name__)

# Cache last phrase per user for vocab save: {user_id: {"phrase": ..., "translation": ...}}
_phrase_cache: dict[int, dict] = {}


async def generate_phrase_of_day(topic: str = "general") -> dict | None:
    topic_hint = f"Topic context: {topic}." if topic != "general" else ""
    result = await ask_groq(
        PHRASE_OF_DAY_SYSTEM,
        f"{topic_hint} Generate a fresh, practical idiom or colloquial phrase.",
    )
    return result


def cache_phrase(user_id: int, phrase: dict):
    _phrase_cache[user_id] = phrase


def get_cached_phrase(user_id: int) -> dict | None:
    return _phrase_cache.get(user_id)


def phrase_keyboard():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ В словарь", callback_data="vocab:phrase_save")],
    ])


def format_phrase_message(phrase: dict) -> str:
    sep = "=" * 30
    lines = [sep, "📖 Фраза дня", ""]

    lines.append(f'"{phrase["phrase"]}"')
    lines.append(f'📝 {phrase["translation"]}')
    lines.append("")

    if phrase.get("origin"):
        lines.append(f"🏛 История: {phrase['origin']}")
        lines.append("")

    lines.append(f"💡 Смысл: {phrase['meaning']}")
    lines.append("")

    examples = phrase.get("examples", [])
    if examples:
        lines.append("📌 Примеры:")
        for ex in examples:
            lines.append(f"  • {ex['en']}")
            lines.append(f"    ({ex['ru']})")
        lines.append("")

    if phrase.get("usage_tip"):
        lines.append(f"✅ {phrase['usage_tip']}")

    if phrase.get("avoid_mistake"):
        lines.append(f"⚠️ {phrase['avoid_mistake']}")

    lines.append(sep)
    return "\n".join(lines)
