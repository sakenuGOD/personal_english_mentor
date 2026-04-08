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
    name = message.from_user.first_name or "друг"
    await message.answer(
        f"Hey, {name}! 👋\n\n"
        "Я помогу тебе с английским прямо в Telegram.\n\n"
        "Подключи меня как Business-бота — буду проверять твои сообщения в чатах и объяснять ошибки.\n\n"
        "Настройки → Telegram Business → Чат-боты → выбери меня\n\n"
        "Или просто используй кнопки ниже 👇",
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
    await message.answer("📊 Прогресс:", reply_markup=progress_keyboard())


@router.message(Command("mistakes"))
async def cmd_mistakes(message: Message, state: FSMContext):
    await state.clear()
    # Support `/mistakes <keyword>` search
    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) > 1:
        keyword = args[1].strip().lower()
        from bot.db.models import Error
        from sqlalchemy import or_
        from bot.services.stats import get_category_name
        async with async_session() as session:
            errors = (await session.execute(
                select(Error)
                .where(
                    Error.user_id == message.from_user.id,
                    or_(
                        Error.original_text.ilike(f"%{keyword}%"),
                        Error.corrected_text.ilike(f"%{keyword}%"),
                        Error.category.ilike(f"%{keyword}%"),
                        Error.rule_name.ilike(f"%{keyword}%"),
                    )
                )
                .order_by(Error.created_at.desc())
                .limit(10)
            )).scalars().all()
        if not errors:
            await message.answer(f"🔍 По запросу «{keyword}» ничего не найдено.")
            return
        lines = [f"🔍 Поиск «{keyword}» ({len(errors)}):\n"]
        for e in errors:
            lines.append(f"❌ {e.original_text} → ✅ {e.corrected_text}")
            lines.append(f"   {get_category_name(e.category)}")
            lines.append("")
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n..."
        await message.answer(text, reply_markup=mistakes_keyboard())
        return
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
