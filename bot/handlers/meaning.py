from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from bot.db.database import async_session
from bot.db.models import User
from bot.services.groq_client import ask_groq
from bot.utils.prompts import MEANING_SYSTEM, get_topic_hint
from bot.keyboards.inline import meaning_result_keyboard, explain_save_keyboard
router = Router()
logger = logging.getLogger(__name__)


class MeaningStates(StatesGroup):
    waiting_phrase = State()


@router.message(F.text == "🤔 Что имел ввиду")
async def start_meaning(message: Message, state: FSMContext):
    await state.set_state(MeaningStates.waiting_phrase)
    await message.answer("🤔 Скинь фразу на английском — объясню что имелось ввиду:")


@router.message(MeaningStates.waiting_phrase)
async def process_meaning(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправь текст.")
        return

    await message.answer("🤔 Разбираю...")

    # Get user topic
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == message.from_user.id))
        user = result.scalar_one_or_none()
    topic = user.topic_pack if user else "general"
    prompt = MEANING_SYSTEM + get_topic_hint(topic)

    result = await ask_groq(prompt, message.text)

    if not result:
        await message.answer("⚠️ Сервис временно недоступен.")
        await state.clear()
        return

    lines = []

    # Translation first
    translation = result.get("translation", "")
    if translation:
        lines.append(f"💬 \"{message.text}\"")
        lines.append(f"📝 {translation}")
        lines.append("")

    # What they meant (if not obvious)
    meaning = result.get("meaning")
    if meaning:
        lines.append(f"🧠 {meaning}")
        lines.append("")

    # Tone
    tone = result.get("tone", "")
    if tone:
        lines.append(f"🎭 Тон: {tone}")
        lines.append("")

    # Word breakdown (only non-obvious)
    word_breakdown = result.get("word_breakdown", [])
    if word_breakdown:
        lines.append("🔤 Разбор:")
        for wb in word_breakdown:
            word = wb.get("word", "")
            wmean = wb.get("meaning", "")
            is_slang = wb.get("is_slang", False)
            note = wb.get("note")
            slang_tag = " [сленг]" if is_slang else ""
            lines.append(f"  • {word}{slang_tag} — {wmean}")
            if note:
                lines.append(f"    ↳ {note}")
        lines.append("")

    # How to reply — the most useful part
    replies = result.get("how_to_reply", [])
    if replies:
        lines.append("💡 Как ответить:")
        for r in replies[:3]:
            lines.append(f"  • {r}")
        lines.append("")

    # Cultural note
    cultural = result.get("cultural_note")
    if cultural:
        lines.append(f"🌍 {cultural}")

    await state.clear()

    # Build keyboard with word save buttons + navigation
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    if word_breakdown:
        # Cache breakdown for vocab save callback
        from bot.handlers.business import _explain_cache
        _explain_cache[message.from_user.id] = word_breakdown
        for i, wb in enumerate(word_breakdown[:5]):
            w = wb.get("word", "")
            if w:
                rows.append([InlineKeyboardButton(text=f"➕ {w}", callback_data=f"vocab:explain_save:{i}")])
    rows.append([
        InlineKeyboardButton(text="🔄 Ещё фразу", callback_data="meaning:another"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="menu"),
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    await message.answer("\n".join(lines), reply_markup=kb)
