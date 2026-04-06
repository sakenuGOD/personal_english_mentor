from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from bot.db.database import async_session
from bot.db.models import User
from bot.keyboards.inline import main_menu_keyboard, settings_keyboard, mistakes_keyboard, progress_keyboard
from bot.services.stats import get_user_stats, format_stats

router = Router()
logger = logging.getLogger(__name__)


async def get_or_create_user(user_id: int, username: str = None, first_name: str = None) -> User:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                id=user_id,
                username=username,
                first_name=first_name,
            )
            session.add(user)
            await session.commit()
        return user


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await message.answer(
        "👋 English Buddy — AI-помощник для английского.\n\n"
        "Что умею:\n"
        "• Проверять тексты и объяснять ошибки\n"
        "• Переводить фразы с вариантами\n"
        "• Объяснять сленг и идиомы\n"
        "• Тренировки по твоим ошибкам\n"
        "• Анализировать произношение\n\n"
        "Просто напиши текст — переведу (RU↔EN).\n\n"
        "/faq — подробная справка по всем кнопкам",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("faq"))
async def cmd_faq(message: Message, state: FSMContext):
    from bot.utils.prompts import FAQ_TEXT
    await message.answer(FAQ_TEXT)


@router.message(Command("settings"))
@router.message(F.text == "⚙️ Настройки")
async def cmd_settings(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == message.from_user.id))
        user = result.scalar_one_or_none()
    if not user:
        await get_or_create_user(message.from_user.id)
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == message.from_user.id))
            user = result.scalar_one_or_none()
    await message.answer("⚙️ Настройки:", reply_markup=settings_keyboard(user))


@router.message(Command("stats"))
@router.message(F.text == "📊 Прогресс")
async def cmd_stats(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        stats = await get_user_stats(session, message.from_user.id)
    await message.answer(format_stats(stats), reply_markup=progress_keyboard())


@router.message(Command("mistakes"))
async def cmd_mistakes(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📓 Журнал ошибок:", reply_markup=mistakes_keyboard())


@router.message(Command("vocab"))
async def cmd_vocab(message: Message, state: FSMContext):
    await state.clear()
    from bot.services.vocabulary import get_vocab_stats, get_words_for_review
    from bot.keyboards.inline import vocab_review_keyboard

    async with async_session() as session:
        stats = await get_vocab_stats(session, message.from_user.id)
        words = await get_words_for_review(session, message.from_user.id, limit=1)

    text = (
        f"📚 Словарь:\n\n"
        f"📖 Всего: {stats['total']}  ✅ Выучено: {stats['mastered']}  🔄 На повторение: {stats['due_today']}\n"
    )

    if words:
        w = words[0]
        text += f"\n🔄 Что значит \"{w.word}\"?"
        await message.answer(text, reply_markup=vocab_review_keyboard(w.id))
    else:
        if stats['total'] == 0:
            text += "\nСловарь пуст. Добавляй через 💡 Слово → ➕ В словарь"
        else:
            text += "\n✅ Все повторены!"
        await message.answer(text)
