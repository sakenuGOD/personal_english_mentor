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
from bot.utils.prompts import CHECK_SYSTEM, get_topic_hint
from bot.keyboards.inline import check_result_keyboard
router = Router()
logger = logging.getLogger(__name__)


class CheckStates(StatesGroup):
    waiting_text = State()


@router.message(F.text == "📝 Проверить текст")
async def start_check(message: Message, state: FSMContext):
    await state.set_state(CheckStates.waiting_text)
    await message.answer("📝 Отправь текст на английском:")


@router.message(CheckStates.waiting_text)
async def process_check(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправь текст.")
        return

    await message.answer("🔍 Анализирую...")

    # Get user topic
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == message.from_user.id))
        user = result.scalar_one_or_none()
    topic = user.topic_pack if user else "general"
    prompt = CHECK_SYSTEM + get_topic_hint(topic)

    result = await ask_groq(prompt, message.text)

    if not result:
        await message.answer("⚠️ Сервис временно недоступен.")
        await state.clear()
        return

    lines = []
    errors = result.get("errors", [])
    error_count = result.get("error_count", len(errors))

    if error_count == 0 and not errors:
        lines.append("✅ Всё правильно!")
    else:
        for i, e in enumerate(errors, 1):
            lines.append(f"{i}. ❌ {e.get('original', '')} → ✅ {e.get('corrected', '')}")
            if e.get("explanation"):
                lines.append(f"   💡 {e['explanation']}")
            lines.append("")

        corrected = result.get("corrected_full", "")
        if corrected:
            lines.append(f"✅ Исправленный текст:\n{corrected}")

    await state.clear()
    await message.answer("\n".join(lines), reply_markup=check_result_keyboard())
