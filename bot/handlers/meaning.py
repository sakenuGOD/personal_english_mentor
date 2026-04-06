from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.services.groq_client import ask_groq
from bot.utils.prompts import MEANING_SYSTEM
from bot.keyboards.inline import meaning_result_keyboard
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
    result = await ask_groq(MEANING_SYSTEM, message.text)

    if not result:
        await message.answer("⚠️ Сервис временно недоступен.")
        await state.clear()
        return

    lines = []

    # Meaning
    meaning = result.get("meaning", "")
    if meaning:
        lines.append(f"💬 {meaning}")
    lines.append("")

    # Literal
    literal = result.get("literal")
    if literal:
        lines.append(f"📝 Дословно: {literal}")

    # Type + tone
    phrase_type = result.get("type", "")
    tone = result.get("tone", "")
    tags = []
    if phrase_type:
        tags.append(phrase_type)
    if tone:
        tags.append(tone)
    if tags:
        lines.append(f"🏷 {' • '.join(tags)}")
    lines.append("")

    # Word breakdown
    word_breakdown = result.get("word_breakdown", [])
    if word_breakdown:
        lines.append("🔤 Разбор по словам:")
        for wb in word_breakdown:
            word = wb.get("word", "")
            wmean = wb.get("meaning", "")
            is_slang = wb.get("is_slang", False)
            origin = wb.get("origin")
            slang_tag = " [сленг]" if is_slang else ""
            lines.append(f"  • {word}{slang_tag} — {wmean}")
            if origin:
                lines.append(f"    ↳ {origin}")
        lines.append("")

    # Examples (ALL in English)
    examples = result.get("examples", [])
    if examples:
        lines.append("📖 Примеры:")
        for ex in examples[:3]:
            lines.append(f"  • {ex}")
        lines.append("")

    # Related
    related = result.get("related", [])
    if related:
        lines.append(f"🔗 Похожие: {', '.join(related[:4])}")

    # Note
    note = result.get("note")
    if note:
        lines.append(f"\n💡 {note}")

    await state.clear()
    await message.answer("\n".join(lines), reply_markup=meaning_result_keyboard())
