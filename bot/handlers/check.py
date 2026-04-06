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

    errors = result.get("errors", [])
    error_count = result.get("error_count", len(errors))
    native_tip = result.get("native_tip")

    if error_count == 0 and not errors and not native_tip:
        await state.clear()
        await message.answer("✅ Всё правильно, звучит естественно!", reply_markup=check_result_keyboard())
        return

    sep = "=" * 30
    lines = [sep, f'"{message.text}"', ""]

    if errors:
        # Corrections
        lines.append("Исправления:")
        for e in errors:
            lines.append(f"  {e.get('original', '')}  →  {e.get('corrected', '')}")

        # Corrected full
        corrected = result.get("corrected_full", "")
        if corrected and corrected.strip().lower() != message.text.strip().lower():
            lines.append(f"\n✅ {corrected}")

        # Explanations
        lines.append(f"\n{'─' * 20}")
        lines.append("Разбор:\n")
        for e in errors:
            explanation = e.get("explanation", "")
            if explanation:
                lines.append(explanation)
                lines.append("")

        # Rule, when, formula from first error
        first = errors[0]
        rule = first.get("rule_name", "")
        if rule:
            lines.append(f"{'─' * 20}")
            lines.append(f"Правило: {rule}\n")

            when = first.get("when_to_use", "")
            if when:
                lines.append(f"Когда: {when}\n")

            formula = first.get("formula", "")
            if formula:
                lines.append(f"Формула: {formula}")

    # Native tip
    if native_tip:
        if errors:
            lines.append("")
        lines.append(f"{'─' * 20}")
        lines.append("Так звучит естественнее:\n")
        lines.append(f"  → {native_tip}")

    lines.append(f"\n{sep}")

    await state.clear()
    await message.answer("\n".join(lines), reply_markup=check_result_keyboard())
