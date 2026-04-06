from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from bot.services.groq_client import ask_groq_text_chat
from bot.utils.prompts import AI_CHAT_SYSTEM
from bot.keyboards.inline import ai_chat_keyboard
from bot.db.database import async_session
from bot.db.models import Error, Message as DbMessage, User, GrammarUsage

router = Router()
logger = logging.getLogger(__name__)


class AiChatStates(StatesGroup):
    chatting = State()


async def _get_user_context(user_id: int) -> str:
    """Build a context string from user's error history and stats."""
    async with async_session() as session:
        # Get user info
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return ""

        # Get recent errors (last 30)
        errors_result = await session.execute(
            select(Error)
            .where(Error.user_id == user_id)
            .order_by(Error.created_at.desc())
            .limit(30)
        )
        errors = errors_result.scalars().all()

        # Get error category counts
        cat_result = await session.execute(
            select(Error.category, func.count(Error.id))
            .where(Error.user_id == user_id)
            .group_by(Error.category)
            .order_by(func.count(Error.id).desc())
        )
        categories = cat_result.all()

        # Get total message stats
        msg_result = await session.execute(
            select(
                func.count(DbMessage.id),
                func.sum(DbMessage.error_count),
            ).where(DbMessage.user_id == user_id)
        )
        msg_stats = msg_result.one()
        total_msgs = msg_stats[0] or 0
        total_errors = msg_stats[1] or 0

        # Get grammar constructions
        grammar_result = await session.execute(
            select(GrammarUsage)
            .where(GrammarUsage.user_id == user_id)
            .order_by(GrammarUsage.times_used.desc())
            .limit(10)
        )
        grammar = grammar_result.scalars().all()

    parts = []
    parts.append(f"XP: {user.xp}, уровень: {user.level}, streak: {user.streak} дней")
    parts.append(f"Всего сообщений: {total_msgs}, ошибок: {total_errors}")

    if categories:
        cat_lines = [f"  {cat}: {cnt}" for cat, cnt in categories if cat]
        if cat_lines:
            parts.append("Категории ошибок:\n" + "\n".join(cat_lines))

    if errors:
        err_lines = []
        for e in errors[:15]:
            err_lines.append(f"  {e.original_text} -> {e.corrected_text} ({e.category}, {e.rule_name})")
        parts.append("Последние ошибки:\n" + "\n".join(err_lines))

    if grammar:
        g_lines = [f"  {g.construction}: {g.times_used}x" for g in grammar]
        parts.append("Грамматические конструкции:\n" + "\n".join(g_lines))

    return "\n".join(parts)


@router.message(F.text == "💬 AI Чат")
async def start_ai_chat(message: Message, state: FSMContext):
    await state.set_state(AiChatStates.chatting)
    await state.update_data(chat_history=[])
    await message.answer(
        "💬 Спрашивай что угодно про английский.\n"
        "Можешь спросить про свои ошибки — я знаю твою историю.\n"
        "Для выхода — «Меню».",
        reply_markup=ai_chat_keyboard(),
    )


@router.message(AiChatStates.chatting)
async def process_ai_chat(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправь текст.")
        return

    await message.answer("💬 Думаю...")

    data = await state.get_data()
    history = data.get("chat_history", [])

    # Check if user is asking about their errors/stats/progress
    user_text_lower = message.text.lower()
    db_keywords = ["ошибк", "ошибок", "ошибки", "мои ошибки", "какие у меня", "статистик",
                    "прогресс", "уровень", "слабые", "сильные", "что я делаю не так",
                    "мой уровень", "что мне учить", "над чем работать", "mistakes", "errors",
                    "my level", "my progress", "weak", "что исправить"]
    needs_db = any(kw in user_text_lower for kw in db_keywords)

    system = AI_CHAT_SYSTEM
    if needs_db:
        user_context = await _get_user_context(message.from_user.id)
        if user_context:
            system = AI_CHAT_SYSTEM + "\n\nДанные пользователя из базы:\n" + user_context

    messages = [{"role": "system", "content": system}]
    for msg in history[-10:]:
        messages.append(msg)
    messages.append({"role": "user", "content": message.text})

    result = await ask_groq_text_chat(messages)

    if not result:
        await message.answer("⚠️ Сервис временно недоступен.")
        return

    history.append({"role": "user", "content": message.text})
    history.append({"role": "assistant", "content": result})
    await state.update_data(chat_history=history)

    # Split long messages
    if len(result) <= 4096:
        await message.answer(result, reply_markup=ai_chat_keyboard())
    else:
        chunks = []
        current = ""
        for line in result.split("\n"):
            if len(current) + len(line) + 1 > 4000:
                chunks.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line
        if current:
            chunks.append(current)
        for i, chunk in enumerate(chunks):
            kb = ai_chat_keyboard() if i == len(chunks) - 1 else None
            await message.answer(chunk, reply_markup=kb)
