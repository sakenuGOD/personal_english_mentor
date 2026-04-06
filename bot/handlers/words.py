from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.services.groq_client import ask_groq
from bot.utils.prompts import WORD_SUGGEST_SYSTEM
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
    result = await ask_groq(WORD_SUGGEST_SYSTEM, word)

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
