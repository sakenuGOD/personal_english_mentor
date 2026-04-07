from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from sqlalchemy import insert
from bot.db.database import async_session
from bot.db.models import User, WordCache
from bot.services.groq_client import ask_groq
from bot.utils.prompts import WORD_SUGGEST_SYSTEM, get_topic_hint
from bot.keyboards.inline import word_result_keyboard
router = Router()
logger = logging.getLogger(__name__)


class WordStates(StatesGroup):
    waiting_word = State()


@router.message(F.text == "💡 Слово")
async def start_words(message: Message, state: FSMContext):
    await state.set_state(WordStates.waiting_word)
    await message.answer("💡 Введи слово (рус/англ):")


@router.message(WordStates.waiting_word)
async def process_word(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправь слово.")
        return

    word = message.text.strip().lower()
    await message.answer("💡 Ищу...")

    # Check cache first
    async with async_session() as session:
        cached = await session.execute(select(WordCache).where(WordCache.word == word))
        cached_row = cached.scalar_one_or_none()

    if cached_row:
        result = cached_row.data
        logger.info(f"Word cache hit: {word}")
    else:
        # Get user topic
        async with async_session() as session:
            u = await session.execute(select(User).where(User.id == message.from_user.id))
            user = u.scalar_one_or_none()
        topic = user.topic_pack if user else "general"
        prompt = WORD_SUGGEST_SYSTEM + get_topic_hint(topic)
        result = await ask_groq(prompt, word)

        # Save to cache
        if result:
            try:
                async with async_session() as session:
                    session.add(WordCache(word=word, data=result))
                    await session.commit()
            except Exception:
                pass  # duplicate key — fine

    if not result:
        await message.answer("⚠️ Сервис временно недоступен.")
        await state.clear()
        return

    lines = []
    w = result.get("word", word)
    transcription = result.get("transcription", "")
    translation = result.get("translation", "")

    lines.append(f"💡 {w} {transcription}")
    lines.append(f"📝 {translation}\n")

    synonyms = result.get("synonyms", [])
    if synonyms:
        lines.append("🔤 Синонимы:")
        for s in synonyms:
            if isinstance(s, dict):
                ru = f" ({s.get('russian', '')})" if s.get('russian') else ""
                lines.append(f"  • {s.get('word', '')}{ru}")
            else:
                lines.append(f"  • {s}")
        lines.append("")

    examples = result.get("examples", [])
    if examples:
        lines.append("📖 Примеры:")
        for ex in examples[:3]:
            lines.append(f"  • {ex}")
        lines.append("")

    collocations = result.get("collocations", [])
    if collocations:
        lines.append(f"🔗 Сочетания: {', '.join(collocations)}")

    usage_note = result.get("usage_note")
    if usage_note:
        lines.append(f"\n💡 {usage_note}")

    await state.clear()
    await message.answer("\n".join(lines), reply_markup=word_result_keyboard(w))
