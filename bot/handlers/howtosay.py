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
from bot.utils.prompts import HOWTOSAY_SYSTEM, get_topic_hint
from bot.keyboards.inline import howtosay_result_keyboard
router = Router()
logger = logging.getLogger(__name__)


class HowToSayStates(StatesGroup):
    waiting_phrase = State()


@router.message(F.text == "🔄 Как сказать")
async def start_howtosay(message: Message, state: FSMContext):
    await state.set_state(HowToSayStates.waiting_phrase)
    await message.answer("🔄 Напиши фразу на русском:")


@router.message(HowToSayStates.waiting_phrase)
async def process_howtosay(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправь фразу.")
        return

    await message.answer("🔄 Перевожу...")

    # Get user topic
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == message.from_user.id))
        user = result.scalar_one_or_none()
    topic = user.topic_pack if user else "general"
    prompt = HOWTOSAY_SYSTEM + get_topic_hint(topic)

    result = await ask_groq(prompt, message.text)

    if not result:
        await state.clear()
        await message.answer("⚠️ Попробуй ещё раз позже.", reply_markup=howtosay_result_keyboard())
        return

    register_emojis = {
        "casual": "😎 Casual",
        "neutral": "👔 Neutral",
        "formal": "🎩 Formal",
        "slang": "🔥 Slang",
    }

    lines = [f"🔄 \"{message.text}\"\n"]
    for v in result.get("variants", []):
        reg = register_emojis.get(v.get("register", ""), v.get("register", ""))
        lines.append(f"{reg}: {v.get('text', '')}")
        if v.get("note"):
            lines.append(f"   ↳ {v['note']}")
        lines.append("")

    trap = result.get("literal_trap")
    if trap:
        lines.append(f"⚠️ {trap}\n")

    tip = result.get("context_tip", "")
    if tip:
        lines.append(f"💡 {tip}")

    await state.clear()
    await message.answer("\n".join(lines), reply_markup=howtosay_result_keyboard())
