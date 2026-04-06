from __future__ import annotations

import logging
from aiogram import Router
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from bot.services.groq_client import ask_groq
from bot.utils.prompts import TRANSLATE_SYSTEM
router = Router()
logger = logging.getLogger(__name__)


@router.inline_query()
async def handle_inline(query: InlineQuery):
    text = query.query.strip()
    if not text or len(text) < 2:
        return

    result = await ask_groq(TRANSLATE_SYSTEM, text)
    if not result:
        return

    translation = result.get("translation", "")
    source = result.get("source_lang", "")

    if not translation:
        return

    results = [
        InlineQueryResultArticle(
            id="translate",
            title=f"{'🇬🇧' if source == 'ru' else '🇷🇺'} {translation}",
            description=f"Перевод: {text}",
            input_message_content=InputTextMessageContent(message_text=translation),
        )
    ]
    await query.answer(results, cache_time=60, is_personal=True)
