from __future__ import annotations

import logging

from bot.services.groq_client import ask_groq
from bot.utils.prompts import PHRASE_OF_DAY_SYSTEM

logger = logging.getLogger(__name__)

# Cache last phrase per user for vocab save: {user_id: {"phrase": ..., "translation": ...}}
_phrase_cache: dict[int, dict] = {}

# Recent phrases to avoid repeats (global, keeps last 30)
_recent_phrases: list[str] = []
MAX_RECENT = 30


async def generate_phrase_of_day(topic: str = "general") -> dict | None:
    topic_hint = f"Topic context: {topic}." if topic != "general" else ""
    avoid = ""
    if _recent_phrases:
        avoid = f"\n\nDo NOT use these phrases (already sent recently): {', '.join(_recent_phrases[-15:])}"
    result = await ask_groq(
        PHRASE_OF_DAY_SYSTEM,
        f"{topic_hint} Generate a fresh, practical idiom or colloquial phrase.{avoid}",
    )
    if result and result.get("phrase"):
        _recent_phrases.append(result["phrase"])
        if len(_recent_phrases) > MAX_RECENT:
            _recent_phrases.pop(0)
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
    sep = "━" * 24
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
