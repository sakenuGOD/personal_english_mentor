from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, update

from bot.db.database import async_session
from bot.db.models import User, Error, Vocabulary
from bot.keyboards.inline import (
    settings_keyboard, correction_mode_keyboard, topic_pack_keyboard,
    main_menu_keyboard, vocab_answer_keyboard, mistakes_keyboard,
    progress_keyboard, workout_menu_keyboard, roleplay_scenarios_keyboard,
)
from bot.handlers.check import CheckStates
from bot.handlers.howtosay import HowToSayStates
from bot.handlers.words import WordStates
from bot.handlers.meaning import MeaningStates
from bot.handlers.roleplay import begin_roleplay, finish_roleplay, RoleplayStates
from bot.services.vocabulary import add_word, review_word, get_words_for_review
from bot.services.gamification import add_xp
from bot.config import XP_NEW_WORD, XP_WORD_REMEMBERED
router = Router()
logger = logging.getLogger(__name__)

ERRORS_PER_PAGE = 5


# ─── Menu ───
@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Выбери действие:", reply_markup=main_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


# ─── Check ───
@router.callback_query(F.data == "check:another")
async def cb_check_another(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CheckStates.waiting_text)
    await callback.message.answer("📝 Отправь текст на английском:")
    await callback.answer()


# ─── How to say ───
@router.callback_query(F.data == "how:another")
async def cb_how_another(callback: CallbackQuery, state: FSMContext):
    await state.set_state(HowToSayStates.waiting_phrase)
    await callback.message.answer("🔄 Напиши фразу на русском:")
    await callback.answer()


# ─── Meaning ───
@router.callback_query(F.data == "meaning:another")
async def cb_meaning_another(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MeaningStates.waiting_phrase)
    await callback.message.answer("🤔 Скинь фразу на английском:")
    await callback.answer()


# ─── Words ───
@router.callback_query(F.data.startswith("word:add:"))
async def cb_word_add(callback: CallbackQuery):
    word = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id
    async with async_session() as session:
        result = await add_word(session, user_id, word, "", "")
    if result:
        async with async_session() as session:
            await add_xp(session, user_id, XP_NEW_WORD, "word_added")
        await callback.answer(f"✅ '{word}' добавлено! +{XP_NEW_WORD} XP")
    else:
        await callback.answer(f"'{word}' уже в словаре")


# ─── Progress ───
@router.callback_query(F.data == "progress:back")
async def cb_progress_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.services.stats import get_user_stats, format_stats
    async with async_session() as session:
        stats = await get_user_stats(session, callback.from_user.id)
    await callback.message.answer(format_stats(stats), reply_markup=progress_keyboard())


@router.callback_query(F.data == "progress:vocab")
async def cb_progress_vocab(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.services.vocabulary import get_vocab_stats, get_words_for_review
    from bot.keyboards.inline import vocab_review_keyboard

    async with async_session() as session:
        stats = await get_vocab_stats(session, callback.from_user.id)
        words = await get_words_for_review(session, callback.from_user.id, limit=1)

    text = (
        f"📚 Словарь:\n\n"
        f"📖 Всего: {stats['total']}  ✅ Выучено: {stats['mastered']}  🔄 На повторение: {stats['due_today']}\n"
    )

    if words:
        w = words[0]
        text += f"\n🔄 Что значит \"{w.word}\"?"
        await callback.message.answer(text, reply_markup=vocab_review_keyboard(w.id))
    else:
        if stats['total'] == 0:
            text += "\nСловарь пуст. Добавляй через 💡 Слово → ➕ В словарь"
        else:
            text += "\n✅ Все повторены!"
        await callback.message.answer(text)


@router.callback_query(F.data == "progress:mistakes")
async def cb_progress_mistakes(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("📓 Журнал ошибок:", reply_markup=mistakes_keyboard())


@router.callback_query(F.data == "progress:workout_menu")
async def cb_progress_workout_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("🎯 Выбери тренировку:", reply_markup=workout_menu_keyboard())


@router.callback_query(F.data == "workout:test")
async def cb_workout_test(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.handlers.workout import start_workout
    await start_workout(callback, state, callback.from_user.id)


@router.callback_query(F.data.startswith("workout:config:count:"))
async def cb_workout_config_count(callback: CallbackQuery, state: FSMContext):
    count = int(callback.data.split(":")[-1])
    await state.update_data(workout_count=count)
    from bot.handlers.workout import WorkoutStates
    await state.set_state(WorkoutStates.config_hints)
    from bot.keyboards.inline import workout_hints_keyboard
    await callback.message.answer(f"📊 Вопросов: {count}\n\n💡 С подсказками или без?", reply_markup=workout_hints_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("workout:config:hints:"))
async def cb_workout_config_hints(callback: CallbackQuery, state: FSMContext):
    hints = callback.data.split(":")[-1] == "yes"
    data = await state.get_data()
    count = data.get("workout_count", 5)
    user_id = data.get("workout_user_id", callback.from_user.id)
    workout_type = data.get("workout_type", "errors")
    await callback.answer()
    if workout_type == "general":
        from bot.handlers.workout import _generate_and_start_general
        await _generate_and_start_general(callback.message, state, count, hints)
    else:
        from bot.handlers.workout import _generate_and_start_workout
        await _generate_and_start_workout(callback.message, state, user_id, count, hints)


@router.callback_query(F.data == "workout:general")
async def cb_workout_general(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.handlers.workout import start_general_workout
    await start_general_workout(callback, state, callback.from_user.id)


@router.callback_query(F.data == "workout:level_test")
async def cb_workout_level_test(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.handlers.workout import start_level_test
    await start_level_test(callback, state, callback.from_user.id)


@router.callback_query(F.data == "workout:roleplay")
async def cb_workout_roleplay(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "🎭 Выбери сценарий для диалога:",
        reply_markup=roleplay_scenarios_keyboard(),
    )


@router.callback_query(F.data == "workout:skip")
async def cb_workout_skip(callback: CallbackQuery, state: FSMContext):
    from bot.handlers.workout import WorkoutStates, _format_task, _format_level_q
    current_state = await state.get_state()
    data = await state.get_data()
    await callback.answer()

    # Error workout skip
    if current_state == WorkoutStates.answering.state:
        tasks = data.get("tasks", [])
        current = data.get("current", 0)
        total = data.get("total", 0)
        correct = data.get("correct", 0)
        task = tasks[current] if current < len(tasks) else None
        answer = task.get("answer", "") if task else ""
        next_idx = current + 1
        await state.update_data(current=next_idx)

        text = f"⏭ {answer}"
        if next_idx >= total:
            text += f"\n\n🏁 Результат: {correct}/{total}"
            from bot.keyboards.inline import workout_done_keyboard
            await callback.message.answer(text, reply_markup=workout_done_keyboard())
            await state.clear()
        else:
            text += "\n\n" + _format_task(tasks[next_idx], next_idx + 1, total)
            from bot.keyboards.inline import workout_skip_keyboard
            await callback.message.answer(text, reply_markup=workout_skip_keyboard())
        return

    # Level test skip — works for grammar, vocab, reading phases
    tasks_map = {
        WorkoutStates.level_grammar.state: ("grammar_tasks", "grammar_correct", "grammar_answers"),
        WorkoutStates.level_vocab.state: ("vocab_tasks", "vocab_correct", "vocab_answers"),
        WorkoutStates.level_reading.state: ("reading_tasks", "reading_correct", "reading_answers"),
    }

    if current_state in tasks_map:
        tasks_key, correct_key, answers_key = tasks_map[current_state]
        tasks = data.get(tasks_key, [])
        current = data.get("current", 0)
        answers = data.get(answers_key, [])

        if current < len(tasks):
            task = tasks[current]
            answers.append({"level": task.get("level", ""), "correct": False, "topic": task.get("topic", "")})
            next_idx = current + 1
            await state.update_data(current=next_idx, **{answers_key: answers})

            text = f"⏭ {task.get('answer', '')}"
            if next_idx < len(tasks):
                text += "\n\n" + _format_level_q(tasks[next_idx], next_idx + 1, len(tasks))
                from bot.keyboards.inline import workout_skip_keyboard
                await callback.message.answer(text, reply_markup=workout_skip_keyboard())
            else:
                await callback.message.answer(f"{text}\n\n✅ Этап завершён")
                # Trigger next phase by sending a synthetic message won't work cleanly
                # Instead, just move to next phase inline
                await _advance_level_phase(callback, state, current_state)


async def _advance_level_phase(callback: CallbackQuery, state: FSMContext, current_phase: str):
    """Move to next phase of level test after skip completes a phase."""
    from bot.handlers.workout import WorkoutStates, _format_level_q, _start_reading_phase, _start_writing_phase
    if current_phase == WorkoutStates.level_grammar.state:
        # Start vocab
        from bot.services.groq_client import ask_groq
        from bot.handlers.workout import LEVEL_TEST_VOCAB
        await callback.message.answer("⏳ Генерирую лексический тест...")
        result = await ask_groq(LEVEL_TEST_VOCAB, "Generate vocabulary test")
        if result and result.get("tasks"):
            tasks = result["tasks"]
            await state.set_state(WorkoutStates.level_vocab)
            await state.update_data(vocab_tasks=tasks, current=0, vocab_correct=0)
            text = "2️⃣ ЛЕКСИКА\n\n" + _format_level_q(tasks[0], 1, len(tasks))
            from bot.keyboards.inline import workout_skip_keyboard
            await callback.message.answer(text, reply_markup=workout_skip_keyboard())
        else:
            await _start_reading_phase(callback.message, state)

    elif current_phase == WorkoutStates.level_vocab.state:
        await _start_reading_phase(callback.message, state)

    elif current_phase == WorkoutStates.level_reading.state:
        await _start_writing_phase(callback.message, state)


# ─── Analysis ───
@router.callback_query(F.data == "progress:analysis")
async def cb_progress_analysis(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("🔍 Анализирую твой уровень...")

    from sqlalchemy import func
    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import ANALYSIS_SYSTEM
    from bot.services.stats import get_category_name

    user_id = callback.from_user.id

    async with async_session() as session:
        # Error stats
        error_cats = await session.execute(
            select(Error.category, func.count(Error.id))
            .where(Error.user_id == user_id)
            .group_by(Error.category)
            .order_by(func.count(Error.id).desc())
        )
        cats = error_cats.all()

        # Total errors
        total_errors = await session.execute(
            select(func.count(Error.id)).where(Error.user_id == user_id)
        )
        total_err = total_errors.scalar() or 0

        # Grammar constructions
        from bot.db.models import GrammarUsage, Message
        constructions = await session.execute(
            select(GrammarUsage.construction, GrammarUsage.times_used)
            .where(GrammarUsage.user_id == user_id)
            .order_by(GrammarUsage.times_used.desc())
            .limit(10)
        )
        constr = constructions.all()

        # Messages count
        total_msgs_r = await session.execute(
            select(func.count(Message.id)).where(Message.user_id == user_id)
        )
        total_msgs = total_msgs_r.scalar() or 0

        # Vocab
        vocab_count_r = await session.execute(
            select(func.count(Vocabulary.id)).where(Vocabulary.user_id == user_id)
        )
        vocab_count = vocab_count_r.scalar() or 0

    if total_msgs < 5 and total_err < 3:
        await callback.message.answer(
            "📊 Пока мало данных для анализа.\n"
            "Напиши больше в чатах — бот соберёт статистику и сможет оценить твой уровень."
        )
        return

    # Build analysis prompt
    analysis_input = f"""Error stats (total: {total_err}):
{chr(10).join(f'- {get_category_name(c)}: {n}' for c, n in cats)}

Grammar constructions used:
{chr(10).join(f'- {c}: {n} times' for c, n in constr)}

Total messages: {total_msgs}
Vocabulary size: {vocab_count}"""

    result = await ask_groq(ANALYSIS_SYSTEM, analysis_input)

    if not result:
        await callback.message.answer("⚠️ Не удалось выполнить анализ.")
        return

    lines = [f"🔍 Твой уровень: {result.get('level', '?')}"]
    desc = result.get("level_description", "")
    if desc:
        lines.append(f"   {desc}")
    lines.append("")

    strengths = result.get("strengths", [])
    if strengths:
        lines.append("💪 Сильные стороны:")
        for s in strengths:
            lines.append(f"  • {s}")
        lines.append("")

    weaknesses = result.get("weaknesses", [])
    if weaknesses:
        lines.append("📝 Слабые места:")
        for w in weaknesses:
            lines.append(f"  • {w}")
        lines.append("")

    problem = result.get("main_problem", "")
    if problem:
        lines.append(f"⚠️ Главная проблема: {problem}")
        lines.append("")

    recs = result.get("recommendations", [])
    if recs:
        lines.append("📌 Рекомендации:")
        for r in recs:
            lines.append(f"  • {r}")
        lines.append("")

    next_tips = result.get("next_level_tips", "")
    if next_tips:
        lines.append(f"🚀 Для следующего уровня: {next_tips}")

    await callback.message.answer("\n".join(lines), reply_markup=progress_keyboard())


# ─── Roleplay ───
@router.callback_query(F.data == "role:help")
async def cb_role_help(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "🎭 Диалог-тренировка\n\n"
        "Выбери ситуацию — бот играет роль собеседника (официант, HR, врач и т.д.).\n"
        "Ты общаешься на английском, бот исправляет ошибки по ходу.\n\n"
        "💡 Можно писать на русском если не знаешь как сказать — бот подскажет.\n"
        "В конце — оценка и разбор ошибок."
    )


@router.callback_query(F.data == "role:custom")
async def cb_roleplay_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RoleplayStates.waiting_custom)
    await callback.message.answer("✏️ Опиши ситуацию на русском или английском:")
    await callback.answer()


@router.callback_query(F.data.startswith("role:start:"))
async def cb_roleplay_start(callback: CallbackQuery, state: FSMContext):
    scenario = callback.data.split(":", 2)[2]
    await callback.answer()
    await begin_roleplay(callback.message, state, scenario)


@router.callback_query(F.data == "role:finish")
async def cb_roleplay_finish(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await finish_roleplay(callback, state)


# ─── Settings ───
@router.callback_query(F.data == "settings:mode")
async def cb_settings_mode(callback: CallbackQuery):
    await callback.message.edit_text(
        "⚡ Выбери режим коррекции:",
        reply_markup=correction_mode_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:mode:help")
async def cb_mode_help(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "📖 Режимы коррекции:\n\n"
        "⚡ Агрессивный — ловит всё: запятые, артикли, стиль. Для максимальной точности.\n\n"
        "🎯 Сбалансированный — только реальные ошибки. Не придирается к пунктуации и сленгу.\n\n"
        "🤫 Тихий — исправляет молча, без пояснений. Собирает в дайджест.\n\n"
        "🎓 Учитель — ловит всё + подробные объяснения правил."
    )


@router.callback_query(F.data.startswith("settings:mode:"))
async def cb_set_mode(callback: CallbackQuery):
    mode = callback.data.split(":")[-1]
    if mode == "help":
        return
    mode_names = {"aggressive": "Агрессивный", "balanced": "Сбалансированный", "silent": "Тихий", "teacher": "Учитель"}
    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == callback.from_user.id).values(correction_mode=mode)
        )
        await session.commit()
        result = await session.execute(select(User).where(User.id == callback.from_user.id))
        user = result.scalar_one_or_none()
    await callback.message.edit_text("⚙️ Настройки:", reply_markup=settings_keyboard(user))
    await callback.answer(f"✅ Режим: {mode_names.get(mode, mode.title())}")


@router.callback_query(F.data == "settings:formality")
async def cb_toggle_formality(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == callback.from_user.id))
        user = result.scalar_one_or_none()
        if user:
            user.formality_meter = not user.formality_meter
            await session.commit()
            await session.refresh(user)
    await callback.message.edit_text("⚙️ Настройки:", reply_markup=settings_keyboard(user))
    await callback.answer(f"📊 Формальность: {'ВКЛ' if user.formality_meter else 'ВЫКЛ'}")


@router.callback_query(F.data == "settings:topic")
async def cb_settings_topic(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌐 Выбери тематический пак:",
        reply_markup=topic_pack_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:topic:help")
async def cb_topic_help(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "📖 Тематические паки\n\n"
        "Тема влияет на контекст всех ответов бота:\n"
        "— Как сказать: примеры из твоей сферы\n"
        "— Слово: примеры в контексте темы\n"
        "— Проверка: native tip учитывает контекст\n"
        "— Что имел ввиду: объяснения в контексте\n\n"
        "🌐 Общий — повседневный английский\n"
        "💻 IT — код, стартапы, дев-команды\n"
        "💼 Бизнес — переговоры, письма, презентации\n"
        "✈️ Путешествия — аэропорт, отель, ресторан\n"
        "🏥 Медицина — симптомы, врачи, лекарства\n"
        "🎮 Игры — игровой сленг, стримы"
    )


@router.callback_query(F.data.startswith("settings:topic:"))
async def cb_set_topic(callback: CallbackQuery):
    topic = callback.data.split(":")[-1]
    if topic == "help":
        return
    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == callback.from_user.id).values(topic_pack=topic)
        )
        await session.commit()
        result = await session.execute(select(User).where(User.id == callback.from_user.id))
        user = result.scalar_one_or_none()
    await callback.message.edit_text("⚙️ Настройки:", reply_markup=settings_keyboard(user))
    await callback.answer(f"✅ Тема: {topic.title()}")


@router.callback_query(F.data == "settings:notifications")
async def cb_toggle_notifications(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == callback.from_user.id))
        user = result.scalar_one_or_none()
        if user:
            user.notifications = not user.notifications
            await session.commit()
            await session.refresh(user)
    await callback.message.edit_text("⚙️ Настройки:", reply_markup=settings_keyboard(user))
    await callback.answer(f"🔔 Уведомления: {'ВКЛ' if user.notifications else 'ВЫКЛ'}")


@router.callback_query(F.data == "settings:back")
async def cb_settings_back(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == callback.from_user.id))
        user = result.scalar_one_or_none()
    await callback.message.edit_text("⚙️ Настройки:", reply_markup=settings_keyboard(user))
    await callback.answer()


# ─── Vocabulary review ───
@router.callback_query(F.data.startswith("vocab:show:"))
async def cb_vocab_show(callback: CallbackQuery):
    word_id = int(callback.data.split(":")[-1])
    async with async_session() as session:
        result = await session.execute(select(Vocabulary).where(Vocabulary.id == word_id))
        vocab = result.scalar_one_or_none()
    if not vocab:
        await callback.answer("Слово не найдено")
        return
    text = (
        f"📖 {vocab.word} — {vocab.translation}\n"
        f"📝 {vocab.example}" if vocab.example else f"📖 {vocab.word} — {vocab.translation}"
    )
    await callback.message.edit_text(text, reply_markup=vocab_answer_keyboard(word_id))
    await callback.answer()


@router.callback_query(F.data.startswith("vocab:yes:"))
async def cb_vocab_yes(callback: CallbackQuery):
    word_id = int(callback.data.split(":")[-1])
    async with async_session() as session:
        await review_word(session, word_id, True)
        await add_xp(session, callback.from_user.id, XP_WORD_REMEMBERED, "word_remembered")
    await callback.message.edit_text(f"✅ +{XP_WORD_REMEMBERED} XP")
    await callback.answer()

    async with async_session() as session:
        words = await get_words_for_review(session, callback.from_user.id, limit=1)
    if words:
        from bot.keyboards.inline import vocab_review_keyboard
        w = words[0]
        await callback.message.answer(
            f"🔄 Что значит \"{w.word}\"?",
            reply_markup=vocab_review_keyboard(w.id),
        )


@router.callback_query(F.data.startswith("vocab:no:"))
async def cb_vocab_no(callback: CallbackQuery):
    word_id = int(callback.data.split(":")[-1])
    async with async_session() as session:
        await review_word(session, word_id, False)
        result = await session.execute(select(Vocabulary).where(Vocabulary.id == word_id))
        vocab = result.scalar_one_or_none()
    if vocab:
        await callback.message.edit_text(
            f"📖 {vocab.word} — {vocab.translation}\n"
            f"Вернулось на 1-й уровень."
        )
    await callback.answer()


# ─── Mistakes Journal with Pagination ───
@router.callback_query(F.data.startswith("mistakes:"))
async def cb_mistakes(callback: CallbackQuery, state: FSMContext):
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from bot.services.stats import get_category_name

    parts = callback.data.split(":")
    period = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    # Handle page navigation — use stored period
    if period == "page":
        page = int(parts[2]) if len(parts) > 2 else 0
        data = await state.get_data()
        period = data.get("mistakes_period", "today")

    await state.update_data(mistakes_period=period, mistakes_page=page)
    user_id = callback.from_user.id

    period_names = {"today": "Сегодня", "week": "Неделя", "month": "Месяц", "all": "Все"}

    async with async_session() as session:
        query = select(Error).where(Error.user_id == user_id)

        if period == "today":
            query = query.where(Error.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0))
        elif period == "week":
            query = query.where(Error.created_at >= datetime.utcnow() - timedelta(days=7))
        elif period == "month":
            query = query.where(Error.created_at >= datetime.utcnow() - timedelta(days=30))
        elif period == "categories":
            cat_query = (
                select(Error.category, func.count(Error.id))
                .where(Error.user_id == user_id)
                .group_by(Error.category)
                .order_by(func.count(Error.id).desc())
            )
            cats = (await session.execute(cat_query)).all()
            if not cats:
                await callback.message.edit_text("✅ Ошибок нет!", reply_markup=mistakes_keyboard())
                await callback.answer()
                return
            lines = ["📊 По категориям:\n"]
            for cat, cnt in cats:
                lines.append(f"  • {get_category_name(cat)} — {cnt}")
            await callback.message.edit_text("\n".join(lines), reply_markup=mistakes_keyboard())
            await callback.answer()
            return
        elif period == "repeated":
            rep_query = (
                select(Error.original_text, Error.corrected_text, Error.category, func.count(Error.id).label("cnt"))
                .where(Error.user_id == user_id)
                .group_by(Error.original_text, Error.corrected_text, Error.category)
                .having(func.count(Error.id) >= 2)
                .order_by(func.count(Error.id).desc())
                .limit(10)
            )
            reps = (await session.execute(rep_query)).all()
            if not reps:
                await callback.message.edit_text("✅ Повторяющихся нет!", reply_markup=mistakes_keyboard())
                await callback.answer()
                return
            lines = ["🔄 Повторяющиеся:\n"]
            for orig, corr, cat, cnt in reps:
                lines.append(f"❌ {orig} → ✅ {corr} (×{cnt})")
                lines.append(f"   {get_category_name(cat)}")
                lines.append("")
            await callback.message.edit_text("\n".join(lines), reply_markup=mistakes_keyboard())
            await callback.answer()
            return

        # Count total for pagination
        count_query = select(func.count(Error.id)).where(Error.user_id == user_id)
        if period == "today":
            count_query = count_query.where(Error.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0))
        elif period == "week":
            count_query = count_query.where(Error.created_at >= datetime.utcnow() - timedelta(days=7))
        elif period == "month":
            count_query = count_query.where(Error.created_at >= datetime.utcnow() - timedelta(days=30))

        total_count = (await session.execute(count_query)).scalar() or 0
        total_pages = max(1, (total_count + ERRORS_PER_PAGE - 1) // ERRORS_PER_PAGE)

        errors = (
            await session.execute(
                query.order_by(Error.created_at.desc())
                .offset(page * ERRORS_PER_PAGE)
                .limit(ERRORS_PER_PAGE)
            )
        ).scalars().all()

    if not errors:
        await callback.message.edit_text("✅ Ошибок нет!", reply_markup=mistakes_keyboard())
        await callback.answer()
        return

    lines = [f"📓 {period_names.get(period, period)}:\n"]
    for e in errors:
        lines.append(f"❌ {e.original_text} → ✅ {e.corrected_text}")
        lines.append(f"   {get_category_name(e.category)}")
        lines.append("")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await callback.message.edit_text(text, reply_markup=mistakes_keyboard(page, total_pages))
    await callback.answer()


# ─── Grammar Map ───
@router.callback_query(F.data == "progress:grammar_map")
async def cb_grammar_map(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("⏳ Строю карту грамматики...")
    from bot.services.stats import get_grammar_map
    from bot.keyboards.inline import grammar_map_keyboard
    async with async_session() as session:
        text = await get_grammar_map(session, callback.from_user.id)
    await callback.message.answer(text, reply_markup=grammar_map_keyboard())


# ─── Weekly Insights ───
@router.callback_query(F.data == "progress:weekly")
async def cb_weekly_insights(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("⏳ Собираю инсайты недели...")
    from bot.services.digest import generate_weekly_insights
    async with async_session() as session:
        text = await generate_weekly_insights(session, callback.from_user.id)
    if text:
        await callback.message.answer(text)
    else:
        await callback.message.answer("За эту неделю пока нет достаточно данных. Пообщайся больше!")


# ─── Translation Workout ───
@router.callback_query(F.data == "workout:translation")
async def cb_workout_translation(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.handlers.workout import start_translation_workout
    await start_translation_workout(callback, state, callback.from_user.id)


# ─── Vocab reminder buttons ───
@router.callback_query(F.data == "vocab:start_review")
async def cb_vocab_start_review(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    from bot.services.vocabulary import get_words_for_review
    from bot.keyboards.inline import vocab_review_keyboard
    async with async_session() as session:
        words = await get_words_for_review(session, callback.from_user.id, limit=1)
    if not words:
        await callback.message.answer("✅ Все слова уже повторены!")
        return
    w = words[0]
    await callback.message.answer(
        f"📚 Словарь\n\n🔄 Что значит \"{w.word}\"?",
        reply_markup=vocab_review_keyboard(w.id),
    )


@router.callback_query(F.data == "vocab:remind_later")
async def cb_vocab_remind_later(callback: CallbackQuery):
    await callback.answer("Хорошо, напомню позже")
    await callback.message.edit_reply_markup(reply_markup=None)


# ─── Vocab save from explain breakdown ───
@router.callback_query(F.data.startswith("vocab:explain_save:"))
async def cb_explain_vocab_save(callback: CallbackQuery):
    try:
        idx = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Ошибка")
        return

    user_id = callback.from_user.id
    from bot.handlers.business import _explain_cache
    breakdown = _explain_cache.get(user_id, [])

    if idx >= len(breakdown):
        await callback.answer("Слово больше недоступно")
        return

    w = breakdown[idx]
    word = w.get("word", "")
    translation = w.get("meaning", "")

    if not word:
        await callback.answer("Нет слова для сохранения")
        return

    async with async_session() as session:
        result = await add_word(session, user_id, word, translation, "")

    if result:
        async with async_session() as session:
            await add_xp(session, user_id, XP_NEW_WORD, "word_added")
        await callback.answer(f"✅ '{word}' добавлено! +{XP_NEW_WORD} XP")
    else:
        await callback.answer(f"'{word}' уже в словаре")
