from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from bot.services.groq_client import ask_groq
from bot.utils.prompts import TRANSLATE_SYSTEM

router = Router()
logger = logging.getLogger(__name__)


_SKIP_TRANSLATE = {
    "ok", "okay", "yes", "no", "yeah", "nope", "sure", "thanks", "thank you",
    "bye", "hi", "hello", "hey", "lol", "haha", "nice", "cool", "wow", "omg",
    "np", "ty", "gn", "gm", "wtf", "lmao", "fr", "nah", "yep", "ок", "окей",
    "да", "нет", "ну", "всё", "все", "хм", "ага", "не", "+", "-", "...",
}


@router.message(F.text)
async def auto_translate(message: Message, state: FSMContext):
    """Default handler: translate any text when no FSM state is active."""
    current_state = await state.get_state()
    if current_state is not None:
        return

    text = message.text.strip()
    if text.startswith("/"):
        return

    # Skip too short or single-word junk
    if len(text) < 3:
        return
    if text.lower().strip("!?.,;:)( ") in _SKIP_TRANSLATE:
        return
    # Skip if it's just emoji or numbers
    alpha = sum(1 for c in text if c.isalpha())
    if alpha < 2:
        return

    result = await ask_groq(TRANSLATE_SYSTEM, text)
    if not result:
        await message.answer("⚠️ Не удалось перевести.")
        return

    translation = result.get("translation", "")
    source = result.get("source_lang", "")

    if source == "ru":
        await message.answer(f"🇬🇧 {translation}")
    else:
        await message.answer(f"🇷🇺 {translation}")
