from __future__ import annotations

import logging
import random

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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


class VocabReviewStates(StatesGroup):
    answering = State()


class BalanceStates(StatesGroup):
    waiting_initial = State()


class TopicTestStates(StatesGroup):
    waiting_topic = State()
    waiting_count = State()
    in_test = State()


async def _send_vocab_card(target, state: FSMContext, user_id: int):
    """Pick next due word, randomly choose direction, ask user to type answer."""
    async with async_session() as session:
        words = await get_words_for_review(session, user_id, limit=1)

    if not words:
        await state.clear()
        await target.answer("✅ Все слова повторены! Возвращайся позже.")
        return

    w = words[0]
    # Random direction: True = show EN ask RU, False = show RU ask EN
    en_to_ru = random.random() > 0.5

    if en_to_ru:
        question = f'🔤 Что значит "{w.word}"?\n\nНапиши перевод на русском:'
        correct = w.translation
    else:
        question = f'🇷🇺 Как по-английски:\n\n"{w.translation}"?'
        correct = w.word

    await state.set_state(VocabReviewStates.answering)
    await state.update_data(
        vocab_word_id=w.id,
        vocab_word=w.word,
        vocab_translation=w.translation,
        vocab_correct=correct,
        vocab_en_to_ru=en_to_ru,
        vocab_user_id=user_id,
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    skip_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Не знаю", callback_data="vocab:skip_answer")],
        [InlineKeyboardButton(text="🏁 Закончить", callback_data="vocab:finish_review")],
    ])
    await target.answer(question, reply_markup=skip_kb)


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
    await state.clear()
    await callback.message.answer("📊 Прогресс:", reply_markup=progress_keyboard())


@router.callback_query(F.data == "progress:vocab")
async def cb_progress_vocab(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.services.vocabulary import get_vocab_stats

    async with async_session() as session:
        stats = await get_vocab_stats(session, callback.from_user.id)

    text = (
        f"📚 Словарь:\n\n"
        f"📖 Всего: {stats['total']}  ✅ Выучено: {stats['mastered']}  🔄 На повторение: {stats['due_today']}\n"
    )

    if stats['due_today'] > 0:
        await callback.message.answer(text)
        await _send_vocab_card(callback.message, state, callback.from_user.id)
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
    from datetime import date
    await callback.answer()
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == callback.from_user.id))
        user = result.scalar_one_or_none()
    today = date.today()
    challenge_done = bool(user and user.challenge_last_sent and user.challenge_last_sent >= today)
    await callback.message.answer("🎯 Выбери тренировку:", reply_markup=workout_menu_keyboard(challenge_done))


@router.callback_query(F.data == "workout:test")
async def cb_workout_test(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.handlers.workout import start_workout
    await start_workout(callback, state, callback.from_user.id)


@router.callback_query(F.data.startswith("workout:diff:"))
async def cb_workout_difficulty(callback: CallbackQuery, state: FSMContext):
    diff = callback.data.split(":")[-1]  # easy / medium / hard
    diff_labels = {"easy": "🟢 Лёгкий (A1-A2)", "medium": "🟡 Средний (B1-B2)", "hard": "🔴 Сложный (B2-C1+)"}
    await state.update_data(workout_difficulty=diff)
    await callback.answer()
    from bot.keyboards.inline import workout_count_keyboard
    await callback.message.edit_text(
        f"Сложность: {diff_labels.get(diff, diff)}\n\nСколько вопросов?",
        reply_markup=workout_count_keyboard(),
    )


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


@router.callback_query(F.data == "workout:topic_test")
async def cb_topic_test_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(TopicTestStates.waiting_topic)
    await callback.message.answer(
        "📌 Тест на тему\n\n"
        "Опиши тему или ситуацию на которой хочешь потренироваться.\n\n"
        "Например:\n"
        "  • Job interview in IT\n"
        "  • Talking about my hobbies\n"
        "  • Medical visit\n"
        "  • Business negotiations\n\n"
        "Можно на русском или английском:"
    )


@router.message(TopicTestStates.waiting_topic)
async def cb_topic_test_got_topic(message: Message, state: FSMContext):
    topic = message.text.strip()
    await state.update_data(topic=topic)
    from bot.keyboards.inline import workout_difficulty_keyboard
    await message.answer(
        f"Тема: {topic}\n\nВыбери сложность:",
        reply_markup=workout_difficulty_keyboard(prefix="topictest", back="workout:topic_test"),
    )


@router.callback_query(F.data.startswith("topictest:diff:"))
async def cb_topic_test_difficulty(callback: CallbackQuery, state: FSMContext):
    diff = callback.data.split(":")[-1]
    diff_labels = {"easy": "🟢 Лёгкий (A1-A2)", "medium": "🟡 Средний (B1-B2)", "hard": "🔴 Сложный (B2-C1+)"}
    await state.update_data(workout_difficulty=diff)
    await state.set_state(TopicTestStates.waiting_count)
    await callback.answer()
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    data = await state.get_data()
    topic = data.get("topic", "")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="5", callback_data="topictest:count:5"),
            InlineKeyboardButton(text="10", callback_data="topictest:count:10"),
            InlineKeyboardButton(text="15", callback_data="topictest:count:15"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu")],
    ])
    await callback.message.edit_text(
        f"Тема: {topic} | {diff_labels.get(diff, diff)}\n\nСколько вопросов?",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("topictest:count:"))
async def cb_topic_test_count(callback: CallbackQuery, state: FSMContext):
    count = int(callback.data.split(":")[-1])
    data = await state.get_data()
    topic = data.get("topic", "")
    await callback.answer()
    await callback.message.edit_text(f"Тема: {topic} | Вопросов: {count}\n\n⏳ Генерирую тест...")

    difficulty = data.get("workout_difficulty", "medium")
    diff_map = {"easy": "A1-A2 (simple present/past, basic vocabulary)", "medium": "B1-B2 (mixed tenses, conditionals, passive)", "hard": "B2-C1+ (perfect tenses, complex structures, nuanced vocabulary)"}
    diff_hint = diff_map.get(difficulty, diff_map["medium"])

    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import TOPIC_TEST_SYSTEM
    result = await ask_groq(TOPIC_TEST_SYSTEM, f"Topic: {topic}. Number of questions: {count}. Difficulty level: {diff_hint}")

    if not result or not result.get("questions"):
        await callback.message.answer("⚠️ Не удалось сгенерировать тест. Попробуй ещё раз.")
        await state.clear()
        return

    questions = result.get("questions", [])[:count]
    title = result.get("topic_title", topic)

    await state.set_state(TopicTestStates.in_test)
    await state.update_data(
        questions=questions,
        current_q=0,
        correct=0,
        topic_title=title,
    )
    await callback.message.answer(f"📌 {title}\n{len(questions)} вопросов. Поехали!")
    await _send_topic_question(callback.message, state)


async def _send_topic_question(target, state: FSMContext):
    data = await state.get_data()
    questions = data.get("questions", [])
    idx = data.get("current_q", 0)
    show_mini_lesson = data.get("show_mini_lesson", False)

    if idx >= len(questions):
        return

    q = questions[idx]
    question_text = q.get("question", "")
    options = q.get("options", [])
    mini_lesson = q.get("mini_lesson", "")
    construction = q.get("construction", "")

    lines = []
    if show_mini_lesson and mini_lesson:
        if construction:
            lines.append(f"📖 {construction}")
        lines.append(f"{mini_lesson}\n")

    lines += [f"❓ {idx + 1}/{len(questions)}\n", question_text, ""]
    for i, opt in enumerate(options):
        lines.append(f"  {i + 1}. {opt}")
    lines.append("\nНапиши номер ответа:")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏹ Завершить", callback_data="topictest:stop")],
    ])
    await target.answer("\n".join(lines), reply_markup=kb)


@router.message(TopicTestStates.in_test)
async def cb_topic_test_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    questions = data.get("questions", [])
    idx = data.get("current_q", 0)
    correct_count = data.get("correct", 0)

    if idx >= len(questions):
        await state.clear()
        return

    q = questions[idx]
    options = q.get("options", [])
    answer = q.get("answer", "")
    explanation = q.get("explanation", "")

    user_input = message.text.strip()
    user_answer = None

    # Accept number or text
    if user_input.isdigit():
        n = int(user_input) - 1
        if 0 <= n < len(options):
            user_answer = options[n]
    else:
        # Try to match by text
        for opt in options:
            if user_input.lower() in opt.lower() or opt.lower() in user_input.lower():
                user_answer = opt
                break

    if user_answer is None:
        await message.answer("Напиши номер ответа (1, 2, 3 или 4)")
        return

    is_correct = user_answer == answer
    if is_correct:
        correct_count += 1
        feedback = f"✅ Правильно!\n💡 {explanation}" if explanation else "✅ Правильно!"
    else:
        feedback = f"❌ Неправильно.\nПравильный ответ: {answer}\n💡 {explanation}" if explanation else f"❌ Неправильно. Правильный ответ: {answer}"

    idx += 1
    await state.update_data(current_q=idx, correct=correct_count)

    if idx >= len(questions):
        # Finished
        total = len(questions)
        pct = round(correct_count / total * 100)
        grade = "A" if pct >= 90 else "B" if pct >= 75 else "C" if pct >= 60 else "D" if pct >= 40 else "F"
        title = data.get("topic_title", "")
        final_summary = data.get("final_summary", "")
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Ещё раз", callback_data="curriculum:analyze"),
                InlineKeyboardButton(text="🏠 Меню", callback_data="menu"),
            ],
        ])
        await message.answer(feedback)
        result_lines = [
            f"🏁 {title}",
            f"Результат: {correct_count}/{total} ({pct}%) — {grade}",
        ]
        if final_summary:
            result_lines.append(f"\n📋 Вывод:\n{final_summary}")
        await message.answer("\n".join(result_lines), reply_markup=kb)
        await state.clear()
        return

    await message.answer(feedback)
    await _send_topic_question(message, state)


@router.callback_query(F.data == "topictest:stop")
async def cb_topic_test_stop(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    questions = data.get("questions", [])
    idx = data.get("current_q", 0)
    correct_count = data.get("correct", 0)
    await callback.answer()
    total = len(questions)
    pct = round(correct_count / idx * 100) if idx > 0 else 0
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
    ])
    await callback.message.answer(
        f"Тест прерван.\nОтвечено: {idx}/{total}, правильно: {correct_count} ({pct}%)",
        reply_markup=kb,
    )
    await state.clear()


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
@router.callback_query(F.data == "progress:curriculum")
async def cb_curriculum(callback: CallbackQuery):
    await callback.answer()
    from bot.services.curriculum import get_path_data, format_path_text
    from bot.keyboards.inline import curriculum_keyboard
    async with async_session() as session:
        data = await get_path_data(session, callback.from_user.id)
    text = format_path_text(data)
    kb = curriculum_keyboard(data.get("weak_topics", []))
    await callback.message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("curriculum:page:"))
async def cb_curriculum_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[-1])
    await callback.answer()
    from bot.services.curriculum import get_path_data, format_path_text
    from bot.keyboards.inline import curriculum_keyboard
    async with async_session() as session:
        data = await get_path_data(session, callback.from_user.id)
    text = format_path_text(data)
    kb = curriculum_keyboard(data.get("weak_topics", []), page=page)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "curriculum:analyze")
async def cb_curriculum_analyze(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("🔬 Анализирую все твои ошибки...")

    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import ADAPTIVE_TEST_SYSTEM

    user_id = callback.from_user.id
    async with async_session() as session:
        errors_result = await session.execute(
            select(Error.original_text, Error.corrected_text, Error.rule_name)
            .where(Error.user_id == user_id)
            .order_by(Error.created_at.desc())
            .limit(100)
        )
        errors = errors_result.all()

    if not errors:
        await callback.message.answer("Пока нет ошибок для анализа. Пообщайся в бизнес-чатах!")
        return

    errors_text = "\n".join(
        f'- "{orig}" → "{corr}"' + (f" ({rule})" if rule else "")
        for orig, corr, rule in errors
    )

    result = await ask_groq(ADAPTIVE_TEST_SYSTEM, errors_text)
    if not result or not result.get("questions"):
        await callback.message.answer("⚠️ Не удалось создать тест.")
        return

    questions = result.get("questions", [])
    level = result.get("overall_level", "")
    patterns = result.get("patterns_found", [])
    final_summary = result.get("final_summary", "")

    # Show patterns found
    intro_lines = [f"🎯 Адаптивный тест — {level}\n"]
    if patterns:
        intro_lines.append("Паттерны которые я нашёл:")
        for p in patterns:
            freq = p.get("frequency", "")
            name = p.get("pattern", "")
            example = p.get("example", "")
            intro_lines.append(f"  • {name} ({freq})")
            if example:
                intro_lines.append(f'    "{example}"')
    intro_lines.append(f"\n{len(questions)} вопросов — от лёгкого к сложному. Поехали!")
    await callback.message.answer("\n".join(intro_lines))

    await state.set_state(TopicTestStates.in_test)
    await state.update_data(
        questions=questions,
        current_q=0,
        correct=0,
        topic_title=f"Адаптивный тест ({level})",
        final_summary=final_summary,  # store for end of test
    )
    await _send_topic_question(callback.message, state)


@router.callback_query(F.data.startswith("curriculum:practice:"))
async def cb_curriculum_practice(callback: CallbackQuery, state: FSMContext):
    topic = callback.data.split(":", 2)[2]
    await callback.answer()
    from bot.services.curriculum import TOPIC_INFO
    from bot.services.groq_client import ask_groq

    info = TOPIC_INFO.get(topic, {})
    name = info.get("name", topic)

    await callback.message.answer(f"⏳ Генерирую упражнение на тему «{name}»...")

    from bot.utils.prompts import TOPIC_TEST_SYSTEM
    result = await ask_groq(
        TOPIC_TEST_SYSTEM,
        f"Topic: {name}. Focus specifically on this grammar construction. Number of questions: 5"
    )
    if not result or not result.get("questions"):
        await callback.message.answer("⚠️ Не удалось создать упражнение.")
        return

    questions = result.get("questions", [])
    await state.set_state(TopicTestStates.in_test)
    await state.update_data(
        questions=questions,
        current_q=0,
        correct=0,
        topic_title=name,
    )
    await callback.message.answer(f"📌 {name} — 5 вопросов")
    await _send_topic_question(callback.message, state)


@router.callback_query(F.data == "progress:stats")
async def cb_progress_stats(callback: CallbackQuery, state: FSMContext):
    """Combined paginated stats: overview → weekly → analysis."""
    await callback.answer()
    loading_msg = await callback.message.answer("⏳ Собираю данные и анализирую...")

    from sqlalchemy import func
    from datetime import datetime, timedelta
    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import ANALYSIS_SYSTEM, WEEKLY_INSIGHTS_SYSTEM
    from bot.services.stats import get_category_name, get_user_stats
    from bot.db.models import GrammarUsage, Message as Msg, XpLog
    import json

    user_id = callback.from_user.id

    async with async_session() as session:
        stats = await get_user_stats(session, user_id)
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

        error_cats = (await session.execute(
            select(Error.category, func.count(Error.id))
            .where(Error.user_id == user_id)
            .group_by(Error.category)
            .order_by(func.count(Error.id).desc())
        )).all()

        total_err = stats["total_errors"]
        total_msgs = stats["total_messages"]
        vocab_count = stats["vocab_count"]

        constr = (await session.execute(
            select(GrammarUsage.construction, GrammarUsage.times_used)
            .where(GrammarUsage.user_id == user_id)
            .order_by(GrammarUsage.times_used.desc())
            .limit(10)
        )).all()

        week_ago = datetime.utcnow() - timedelta(days=7)
        prev_week_ago = datetime.utcnow() - timedelta(days=14)

        this_msgs = (await session.execute(
            select(func.count(Msg.id)).where(Msg.user_id == user_id, Msg.created_at >= week_ago)
        )).scalar() or 0
        this_errs = (await session.execute(
            select(func.count(Msg.id)).where(Msg.user_id == user_id, Msg.has_errors == True, Msg.created_at >= week_ago)
        )).scalar() or 0
        prev_msgs = (await session.execute(
            select(func.count(Msg.id)).where(Msg.user_id == user_id, Msg.created_at >= prev_week_ago, Msg.created_at < week_ago)
        )).scalar() or 0
        prev_errs = (await session.execute(
            select(func.count(Msg.id)).where(Msg.user_id == user_id, Msg.has_errors == True, Msg.created_at >= prev_week_ago, Msg.created_at < week_ago)
        )).scalar() or 0
        xp_week = (await session.execute(
            select(func.sum(XpLog.amount)).where(XpLog.user_id == user_id, XpLog.created_at >= week_ago)
        )).scalar() or 0

        top_errors_week = (await session.execute(
            select(Error.original_text, Error.corrected_text, Error.short_explanation, func.count(Error.id).label("cnt"))
            .where(Error.user_id == user_id, Error.created_at >= week_ago)
            .group_by(Error.original_text, Error.corrected_text)
            .order_by(func.count(Error.id).desc())
            .limit(50)
        )).all()

    if total_msgs < 3:
        await loading_msg.delete()
        await callback.message.answer(
            "Пока мало данных.\nПообщайся в бизнес-чатах — соберём статистику.",
            reply_markup=progress_keyboard()
        )
        return

    pages = []

    this_rate = round(this_errs / this_msgs * 100, 1) if this_msgs else 0
    prev_rate = round(prev_errs / prev_msgs * 100, 1) if prev_msgs else None
    all_rate = round(total_err / total_msgs * 100, 1) if total_msgs else 0
    lvl = user.level if user else "newbie"
    xp = user.xp if user else 0
    streak = user.streak if user else 0
    eng_level = user.english_level if user else None

    # trend arrow
    if prev_rate is not None:
        delta = this_rate - prev_rate
        if delta < -1:
            trend_str = f"✅ лучше на {round(abs(delta), 1)}% чем неделю назад"
        elif delta > 1:
            trend_str = f"⚠️ хуже на {round(delta, 1)}% чем неделю назад"
        else:
            trend_str = "без изменений"
    else:
        trend_str = ""

    # ── Page 1: Overview ──
    sep = "─" * 24
    p1 = [f"📊 Статистика\n"]
    header = []
    if eng_level:
        header.append(f"🎓 {eng_level}")
    header.append(f"⚡ {xp} XP")
    header.append(f"🔥 {streak} дн.")
    p1.append("  ".join(header))
    p1.append(sep)
    p1.append(f"💬 Сообщений: {total_msgs}")
    if this_msgs:
        err_line = f"❌ Ошибки за неделю: {this_rate}%"
        if trend_str:
            err_line += f"  {trend_str}"
        p1.append(err_line)
    else:
        p1.append(f"❌ Ошибок в сообщениях: {all_rate}%")

    p1.append(f"📚 Слов в словаре: {vocab_count}")
    p1.append(sep)

    if error_cats:
        p1.append("Где чаще всего ошибаешься:")
        for i, (cat, cnt) in enumerate(error_cats[:5], 1):
            p1.append(f"  {i}. {get_category_name(cat)} — {cnt}×")

    pages.append("\n".join(p1))

    # ── Page 2: Weekly deep-dive with GPT rule ──
    weekly_payload = {
        "this_week": {"messages": this_msgs, "errors": this_errs, "error_rate": this_rate},
        "prev_week": {"messages": prev_msgs, "errors": prev_errs, "error_rate": prev_rate},
        "top_categories": [{"category": c, "count": n} for c, n in error_cats[:5]],
        "xp_earned": xp_week,
    }
    weekly_gpt = await ask_groq(WEEKLY_INSIGHTS_SYSTEM, json.dumps(weekly_payload))

    p2 = ["📅 Неделя — разбор\n"]
    if this_msgs == 0:
        p2.append("Нет данных за эту неделю.")
    else:
        p2.append(f"Сообщений: {this_msgs}  |  Ошибок: {this_errs} ({this_rate}%)")
        if trend_str:
            p2.append(trend_str)
        p2.append(f"XP: +{xp_week}")
        p2.append("")

        if weekly_gpt:
            summary = weekly_gpt.get("summary")
            main_problem = weekly_gpt.get("main_problem")
            trend_text = weekly_gpt.get("trend")
            next_focus = weekly_gpt.get("next_focus")
            if summary:
                p2.append(summary)
                p2.append("")
            if main_problem:
                p2.append(f"🔴 Главная проблема:\n{main_problem}")
                p2.append("")
            if trend_text:
                p2.append(f"📈 Динамика: {trend_text}")
                p2.append("")
            if next_focus:
                p2.append(f"🎯 Фокус на следующей неделе:\n{next_focus}")

    pages.append("\n".join(p2))

    # ── Page 3: GPT Analysis ──
    analysis_input = (
        f"Error stats (total: {total_err}):\n"
        + "\n".join(f"- {get_category_name(c)}: {n}" for c, n in error_cats)
        + f"\n\nGrammar constructions used:\n"
        + "\n".join(f"- {c}: {n} times" for c, n in constr)
        + f"\n\nTotal messages: {total_msgs}, vocab: {vocab_count}, streak: {streak} days"
    )
    gpt = await ask_groq(ANALYSIS_SYSTEM, analysis_input)

    if gpt:
        p3 = [f"🔍 Уровень по данным: {gpt.get('level', '?')}"]
        desc = gpt.get("level_description", "")
        if desc:
            p3.append(f"   {desc}")
        p3.append("")
        summary = gpt.get("summary", "")
        if summary:
            p3.append(summary)
            p3.append("")
        strengths = gpt.get("strengths", [])
        if strengths:
            p3.append("💪 Сильные стороны:")
            for s in strengths:
                p3.append(f"  • {s}")
            p3.append("")
        weaknesses = gpt.get("weaknesses", [])
        if weaknesses:
            p3.append("📌 Слабые места:")
            for w in weaknesses:
                p3.append(f"  • {w}")
            p3.append("")
        plan = gpt.get("action_plan", [])
        if plan:
            p3.append("🎯 Что делать:")
            for i, a in enumerate(plan, 1):
                p3.append(f"  {i}. {a}")
            p3.append("")
        tips = gpt.get("next_level_tips", "")
        if tips:
            p3.append(f"🚀 До следующего уровня:\n   {tips}")
        pages.append("\n".join(p3))
    else:
        pages.append("⚠️ Не удалось выполнить анализ.")

    # Auto-split pages that are too long (>3500 chars)
    final_pages = []
    for p in pages:
        if len(p) <= 3500:
            final_pages.append(p)
        else:
            # Split by lines into chunks
            lines = p.split("\n")
            chunk, chunks = [], []
            for line in lines:
                if len("\n".join(chunk)) + len(line) > 3400:
                    chunks.append("\n".join(chunk))
                    chunk = [line]
                else:
                    chunk.append(line)
            if chunk:
                chunks.append("\n".join(chunk))
            final_pages.extend(chunks)

    await state.update_data(stats_pages=final_pages)

    def stats_kb(page, total):
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"stats:page:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="noop"))
        if page < total - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"stats:page:{page+1}"))
        rows = [nav] if nav else []
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="progress:back")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    await loading_msg.delete()
    await callback.message.answer(final_pages[0], reply_markup=stats_kb(0, len(final_pages)))


@router.callback_query(F.data.startswith("stats:page:"))
async def cb_stats_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[-1])
    await callback.answer()
    fsm = await state.get_data()
    pages = fsm.get("stats_pages", [])
    if not pages:
        await callback.message.answer("Открой статистику заново.")
        return
    total = len(pages)
    page = max(0, min(page, total - 1))
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"stats:page:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"stats:page:{page+1}"))
    kb = InlineKeyboardMarkup(inline_keyboard=[nav, [InlineKeyboardButton(text="◀️ Назад", callback_data="progress:back")]])
    try:
        await callback.message.edit_text(pages[page], reply_markup=kb)
    except Exception:
        await callback.message.answer(pages[page], reply_markup=kb)


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


@router.callback_query(F.data == "settings:usage")
async def cb_settings_usage(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    # First time — ask for initial balance
    if not user or not user.api_balance_initial:
        await state.set_state(BalanceStates.waiting_initial)
        await callback.message.answer(
            "💰 Введи текущий баланс ProxyAPI в долларах:\n\n"
            "Например: 5.00\n\n"
            "(Смотри на proxyapi.ru в личном кабинете)"
        )
        return

    await _show_usage(callback.message, user)


async def _show_usage(target, user):
    from bot.services.groq_client import get_usage_stats
    from datetime import datetime, timedelta

    stats = get_usage_stats()

    # gpt-4o-mini pricing
    IN_PRICE = 0.00000015   # $0.15 per 1M input tokens
    OUT_PRICE = 0.00000060  # $0.60 per 1M output tokens

    def calc_cost(s: dict) -> float:
        return s["in"] * IN_PRICE + s["out"] * OUT_PRICE

    t = stats["today"]
    y = stats["yesterday"]
    total_all = stats["total_all"]
    days_tracked = stats["days_tracked"]

    cost_today = calc_cost(t)
    cost_total = calc_cost(total_all)

    total_tokens = total_all["in"] + total_all["out"]

    lines = ["💰 Расходы и баланс", ""]

    try:
        initial = float(user.api_balance_initial)
        remaining = max(0.0, initial - cost_total)
        set_at = user.api_balance_set_at.strftime("%d.%m") if user.api_balance_set_at else "?"

        # Daily burn rate
        if days_tracked > 0 and cost_total > 0:
            avg_daily_cost = cost_total / days_tracked
            avg_daily_tokens = total_tokens / days_tracked
            est_days = remaining / avg_daily_cost if avg_daily_cost > 0 else 0
            est_until = datetime.now() + timedelta(days=est_days)
        else:
            avg_daily_cost = 0
            avg_daily_tokens = 0
            est_days = 0
            est_until = None

        lines += [
            f"🏦 Баланс: ${initial:.2f} → ${remaining:.4f}",
            f"💸 Потрачено: ~${cost_total:.5f}",
            "",
        ]

        if est_days > 0:
            until_str = est_until.strftime("%d.%m.%Y") if est_until else "?"
            lines += [
                f"📅 Хватит примерно на {int(est_days)} дней",
                f"   (до ~{until_str} при текущем темпе)",
                "",
            ]

        if avg_daily_tokens > 0:
            lines += [
                f"📊 Средний расход в день:",
                f"   {int(avg_daily_tokens):,} токенов / ~${avg_daily_cost:.5f}",
                "",
            ]
    except Exception:
        pass

    # Today breakdown
    lines += [
        "Сегодня:",
        f"  📥 {t['in']:,} вход + 📤 {t['out']:,} выход = {t['in']+t['out']:,} токенов",
        f"  🔢 {t['calls']} запросов  💵 ~${calc_cost(t):.5f}",
    ]

    if y["calls"] > 0:
        lines += [
            "",
            "Вчера:",
            f"  {y['in']+y['out']:,} токенов / {y['calls']} запросов  💵 ~${calc_cost(y):.5f}",
        ]

    if total_all["calls"] > 0 and total_all["calls"] != t["calls"]:
        avg_per_call = total_tokens / total_all["calls"]
        lines += [
            "",
            f"Всего с запуска: {total_tokens:,} токенов / {total_all['calls']} запросов",
            f"В среднем {int(avg_per_call):,} токенов на запрос",
        ]

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить баланс", callback_data="settings:reset_balance")],
    ])
    await target.answer("\n".join(lines), reply_markup=kb)


@router.message(BalanceStates.waiting_initial)
async def cb_balance_input(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", ".")
    try:
        amount = float(text)
        if amount < 0 or amount > 10000:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи корректную сумму, например: 5.00")
        return

    from datetime import datetime
    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == message.from_user.id).values(
                api_balance_initial=str(amount),
                api_balance_set_at=datetime.utcnow(),
            )
        )
        await session.commit()
        result = await session.execute(select(User).where(User.id == message.from_user.id))
        user = result.scalar_one_or_none()

    await state.clear()
    await message.answer(f"✅ Баланс ${amount:.2f} сохранён!")
    await _show_usage(message, user)


@router.callback_query(F.data == "settings:reset_balance")
async def cb_reset_balance(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BalanceStates.waiting_initial)
    await callback.message.answer("💰 Введи новый текущий баланс в долларах:")


@router.callback_query(F.data == "settings:back")
async def cb_settings_back(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == callback.from_user.id))
        user = result.scalar_one_or_none()
    await callback.message.edit_text("⚙️ Настройки:", reply_markup=settings_keyboard(user))
    await callback.answer()


# ─── Vocabulary review ───
@router.message(VocabReviewStates.answering)
async def cb_vocab_typed_answer(message: Message, state: FSMContext):
    """User typed their answer — check it."""
    data = await state.get_data()
    correct = data.get("vocab_correct", "")
    word_id = data.get("vocab_word_id")
    word = data.get("vocab_word", "")
    translation = data.get("vocab_translation", "")
    en_to_ru = data.get("vocab_en_to_ru", True)
    user_id = data.get("vocab_user_id", message.from_user.id)

    user_answer = message.text.strip().lower()
    correct_clean = correct.strip().lower()

    # Simple match: exact or contained (handles "I'm happy" ≈ "happy")
    is_correct = user_answer == correct_clean or correct_clean in user_answer or user_answer in correct_clean

    async with async_session() as session:
        await review_word(session, word_id, is_correct)
        if is_correct:
            await add_xp(session, user_id, XP_WORD_REMEMBERED, "word_remembered")

    if is_correct:
        feedback = f"✅ Правильно! +{XP_WORD_REMEMBERED} XP\n\n{word} — {translation}"
    else:
        feedback = f"❌ Не угадал.\n\n{word} — {translation}"
        if en_to_ru:
            feedback += f"\n\nПравильный перевод: {correct}"
        else:
            feedback += f"\n\nПо-английски: {correct}"

    await message.answer(feedback)
    await _send_vocab_card(message, state, user_id)


@router.callback_query(F.data == "vocab:skip_answer")
async def cb_vocab_skip(callback: CallbackQuery, state: FSMContext):
    """User doesn't know — show answer, count as wrong."""
    data = await state.get_data()
    word_id = data.get("vocab_word_id")
    word = data.get("vocab_word", "")
    translation = data.get("vocab_translation", "")
    user_id = data.get("vocab_user_id", callback.from_user.id)

    if word_id:
        async with async_session() as session:
            await review_word(session, word_id, False)

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"📖 {word} — {translation}\n\nВернулось на 1-й уровень.")
    await _send_vocab_card(callback.message, state, user_id)


@router.callback_query(F.data == "vocab:finish_review")
async def cb_vocab_finish(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("🏁 Повторение закончено. Возвращайся позже!")


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
            lines = ["🔄 Повторяющиеся ошибки:\n"]
            for orig, corr, cat, cnt in reps:
                lines.append(f"❌ {orig}  →  ✅ {corr}  (×{cnt})")
                lines.append(f"   {get_category_name(cat)}")
                lines.append("")
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎯 Потренироваться по этим ошибкам", callback_data="mistakes:practice_repeated")],
                [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
            ])
            await callback.message.edit_text("\n".join(lines), reply_markup=kb)
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
        lines.append(f"❌ {e.original_text}")
        lines.append(f"✅ {e.corrected_text}")
        if e.short_explanation:
            lines.append(f"💡 {e.short_explanation}")
        elif e.category:
            lines.append(f"   {get_category_name(e.category)}")
        lines.append("")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await callback.message.edit_text(text, reply_markup=mistakes_keyboard(page, total_pages))
    await callback.answer()


@router.callback_query(F.data == "mistakes:practice_repeated")
async def cb_mistakes_practice_repeated(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("🎯 Генерирую тест по твоим повторяющимся ошибкам...")

    from sqlalchemy import func
    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import ADAPTIVE_TEST_SYSTEM

    user_id = callback.from_user.id
    async with async_session() as session:
        reps = (await session.execute(
            select(Error.original_text, Error.corrected_text, Error.rule_name)
            .where(Error.user_id == user_id)
            .group_by(Error.original_text, Error.corrected_text, Error.rule_name)
            .having(func.count(Error.id) >= 2)
            .order_by(func.count(Error.id).desc())
            .limit(20)
        )).all()

    if not reps:
        await callback.message.answer("Повторяющихся ошибок пока нет.")
        return

    errors_text = "\n".join(f'- "{orig}" → "{corr}"' + (f" ({rule})" if rule else "") for orig, corr, rule in reps)
    result = await ask_groq(ADAPTIVE_TEST_SYSTEM, errors_text)

    if not result or not result.get("questions"):
        await callback.message.answer("⚠️ Не удалось создать тест.")
        return

    questions = result.get("questions", [])
    summary = result.get("final_summary", "")
    level = result.get("overall_level", "")
    patterns = result.get("patterns_found", [])

    intro = [f"🔁 Тест по повторяющимся ошибкам — {level}\n"]
    if patterns:
        for p in patterns:
            intro.append(f"  • {p.get('pattern', '')} ({p.get('frequency', '')})")
    intro.append(f"\n{len(questions)} вопросов")
    await callback.message.answer("\n".join(intro))

    await state.set_state(TopicTestStates.in_test)
    await state.update_data(questions=questions, current_q=0, correct=0,
                            topic_title=f"Повторяющиеся ошибки ({level})", final_summary=summary)
    await _send_topic_question(callback.message, state)


# ─── Idioms on demand ───
@router.callback_query(F.data == "progress:idioms")
async def cb_idioms(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("⏳ Подбираю фразу...")

    from bot.services.phrase_of_day import generate_phrase_of_day, format_phrase_message, cache_phrase

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == callback.from_user.id))
        user = result.scalar_one_or_none()
    topic = user.topic_pack if user else "general"

    phrase = await generate_phrase_of_day(topic)
    if not phrase:
        await callback.message.answer("⚠️ Не удалось сгенерировать. Попробуй ещё раз.")
        return

    cache_phrase(callback.from_user.id, phrase)
    text = format_phrase_message(phrase)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ В словарь", callback_data="vocab:phrase_save")],
        [
            InlineKeyboardButton(text="🔄 Ещё", callback_data="progress:idioms"),
            InlineKeyboardButton(text="◀️ Назад", callback_data="progress:back"),
        ],
    ])
    await callback.message.answer(text, reply_markup=kb)


# ─── Grammar Map ───
@router.callback_query(F.data == "progress:grammar_map")
async def cb_grammar_map(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("⏳ Строю карту грамматики...")
    from bot.services.stats import get_grammar_map, format_grammar_page
    from bot.keyboards.inline import grammar_map_keyboard
    async with async_session() as session:
        data = await get_grammar_map(session, callback.from_user.id)
    await state.update_data(grammar_map_data=data)
    text, total = format_grammar_page(data, 0)
    await callback.message.answer(text, reply_markup=grammar_map_keyboard(0, total))


@router.callback_query(F.data == "grammar:train_gaps")
async def cb_grammar_train_gaps(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("🎯 Генерирую упражнения на твои пробелы...")

    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import GRAMMAR_GAPS_TEST_SYSTEM
    from bot.services.stats import get_grammar_map

    fsm_data = await state.get_data()
    data = fsm_data.get("grammar_map_data")
    if not data:
        async with async_session() as session:
            data = await get_grammar_map(session, callback.from_user.id)

    never_used = data.get("never_used", [])
    gpt_data = data.get("gpt", {})
    level = gpt_data.get("level_estimate", "B1")

    if not never_used:
        await callback.message.answer("🎉 Нет пробелов — ты использовал все конструкции!")
        return

    from bot.services.stats import CONSTRUCTION_LABELS, CONSTRUCTION_HINTS
    gaps_text = "\n".join(
        f"- {CONSTRUCTION_LABELS.get(c, c)}: {CONSTRUCTION_HINTS.get(c, '')}"
        for c in never_used
    )

    result = await ask_groq(
        GRAMMAR_GAPS_TEST_SYSTEM,
        f"Student level: {level}\n\nNever used constructions:\n{gaps_text}"
    )
    if not result or not result.get("questions"):
        await callback.message.answer("⚠️ Не удалось создать упражнения.")
        return

    questions = result.get("questions", [])
    summary = result.get("final_summary") or result.get("summary", "")

    # Add mini_lesson to each question display — store in questions for rendering
    await state.set_state(TopicTestStates.in_test)
    await state.update_data(
        questions=questions,
        current_q=0,
        correct=0,
        topic_title="Тренировка пробелов",
        final_summary=summary,
        show_mini_lesson=True,
    )
    await callback.message.answer(f"📚 {len(questions)} упражнений — по самым важным пробелам")
    await _send_topic_question(callback.message, state)


@router.callback_query(F.data.startswith("grammar:page:"))
async def cb_grammar_page(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[-1])
    await callback.answer()
    from bot.services.stats import format_grammar_page
    from bot.keyboards.inline import grammar_map_keyboard
    fsm_data = await state.get_data()
    data = fsm_data.get("grammar_map_data")
    if not data:
        # Re-fetch if state lost
        async with async_session() as session:
            from bot.services.stats import get_grammar_map
            data = await get_grammar_map(session, callback.from_user.id)
        await state.update_data(grammar_map_data=data)
    text, total = format_grammar_page(data, page)
    try:
        await callback.message.edit_text(text, reply_markup=grammar_map_keyboard(page, total))
    except Exception:
        await callback.message.answer(text, reply_markup=grammar_map_keyboard(page, total))


# ─── Weekly Insights (kept for scheduler backward compat) ───
@router.callback_query(F.data == "progress:weekly")
async def cb_weekly_insights(callback: CallbackQuery):
    await cb_progress_stats(callback)


# ─── Daily Checkup navigation & practice ───
@router.callback_query(F.data.startswith("checkup:page:"))
async def cb_checkup_page(callback: CallbackQuery):
    await callback.answer()
    page = int(callback.data.split(":")[-1])
    bot = callback.bot
    pages = getattr(bot, "_checkup_pages", {}).get(callback.from_user.id, [])
    if not pages:
        await callback.answer("Данные устарели, запусти чекап заново.", show_alert=True)
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    def checkup_kb(p, total):
        nav = []
        if p > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"checkup:page:{p-1}"))
        if total > 1:
            nav.append(InlineKeyboardButton(text=f"{p+1}/{total}", callback_data="noop"))
        if p < total - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"checkup:page:{p+1}"))
        rows = [nav] if nav else []
        rows.append([InlineKeyboardButton(text="📝 Проработать ошибки", callback_data="checkup:practice")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    await callback.message.edit_text(pages[page], reply_markup=checkup_kb(page, len(pages)))


class CheckupPracticeStates(StatesGroup):
    in_practice = State()


@router.callback_query(F.data == "checkup:practice")
async def cb_checkup_practice(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import CHECKUP_PRACTICE_SYSTEM
    import json

    bot = callback.bot
    checkup_patterns = getattr(bot, "_checkup_patterns", {}).get(callback.from_user.id, [])

    if not checkup_patterns:
        await callback.message.answer("Нет данных чекапа. Практика доступна сразу после получения чекапа.")
        return

    loading = await callback.message.answer("⏳ Составляю упражнения по твоим паттернам ошибок...")
    result = await ask_groq(CHECKUP_PRACTICE_SYSTEM, json.dumps(checkup_patterns, ensure_ascii=False))
    await loading.delete()

    if not result or not result.get("exercises"):
        await callback.message.answer("Не удалось составить упражнения.")
        return

    exercises = result["exercises"]
    await state.set_state(CheckupPracticeStates.in_practice)
    await state.update_data(cp_exercises=exercises, cp_index=0, cp_score=0)
    await _send_checkup_exercise(callback.message, state, exercises, 0)


async def _send_checkup_exercise(message, state, exercises, idx):
    q = exercises[idx]
    total = len(exercises)
    qtype = q.get("type", "fill_blank")
    pattern = q.get("pattern", "")

    lines = [f"📝 Практика {idx+1}/{total}  |  {pattern}\n"]

    if qtype == "translate":
        lines.append(f"🇷🇺 {q.get('prompt_ru', '')}")
        hint = q.get("hint", "")
        if hint:
            lines.append(f"💡 {hint}")
        lines.append("\nПереведи на английский:")
    elif qtype == "fill_blank":
        lines.append(q.get("sentence", ""))
        options = q.get("options", [])
        if options:
            lines.append("")
            for i, opt in enumerate(options, 1):
                lines.append(f"  {i}. {opt}")
        lines.append("\n(напиши номер или вариант)")
    elif qtype == "correct_sentence":
        lines.append("Исправь предложение:")
        lines.append(f"\n❌ {q.get('wrong_sentence', '')}")
        lines.append("\nНапиши правильный вариант:")
    elif qtype == "choose_correct":
        lines.append("Какое предложение правильное?")
        for i, opt in enumerate(q.get("options", []), 1):
            lines.append(f"  {i}. {opt}")
        lines.append("\n(напиши номер)")

    await state.update_data(cp_index=idx)
    await message.answer("\n".join(lines))


@router.message(CheckupPracticeStates.in_practice)
async def cb_checkup_practice_answer(message, state: FSMContext):
    from bot.services.groq_client import ask_groq
    fsm = await state.get_data()
    exercises = fsm.get("cp_exercises", [])
    idx = fsm.get("cp_index", 0)
    score = fsm.get("cp_score", 0)

    if idx >= len(exercises):
        await state.clear()
        return

    q = exercises[idx]
    qtype = q.get("type", "fill_blank")
    user_text = message.text.strip()
    explanation = q.get("explanation", "")

    if qtype == "translate":
        # GPT evaluates free-form translation
        correct_en = q.get("correct_en", "")
        eval_prompt = (
            f"Student translated: \"{user_text}\"\n"
            f"Correct answer: \"{correct_en}\"\n"
            f"Pattern being tested: {q.get('pattern', '')}\n"
            f"Is the student's answer correct or acceptable? "
            f"Respond ONLY in JSON: {{\"ok\": true/false, \"comment\": \"короткое объяснение на русском если неверно\"}}"
        )
        eval_result = await ask_groq("You are a strict English teacher evaluating a translation. Be lenient about word order and synonyms but strict about the grammar pattern being tested.", eval_prompt)
        is_correct = eval_result.get("ok", False) if eval_result else False
        comment = eval_result.get("comment", "") if eval_result else ""

        if is_correct:
            score += 1
            reply = f"✅ Верно!\n✍️ Эталон: {correct_en}"
        else:
            reply = f"❌ Не совсем.\n✍️ Правильно: {correct_en}"
            if comment:
                reply += f"\n💡 {comment}"
        if explanation:
            reply += f"\n\n{explanation}"

    elif qtype == "correct_sentence":
        correct_en = q.get("correct_sentence", "")
        eval_prompt = (
            f"Student wrote: \"{user_text}\"\n"
            f"Correct answer: \"{correct_en}\"\n"
            f"Pattern: {q.get('pattern', '')}\n"
            f"Is the student's correction acceptable? "
            f"Respond ONLY in JSON: {{\"ok\": true/false, \"comment\": \"короткое объяснение на русском если неверно\"}}"
        )
        eval_result = await ask_groq("You are a strict English teacher checking a sentence correction. Be lenient about synonyms but strict about the grammar pattern.", eval_prompt)
        is_correct = eval_result.get("ok", False) if eval_result else False
        comment = eval_result.get("comment", "") if eval_result else ""
        if is_correct:
            score += 1
            reply = f"✅ Верно!\n✍️ Эталон: {correct_en}"
        else:
            reply = f"❌ Не совсем.\n✍️ Правильно: {correct_en}"
            if comment:
                reply += f"\n💡 {comment}"
        if explanation:
            reply += f"\n\n{explanation}"

    elif qtype in ("fill_blank", "choose_correct"):
        from bot.handlers.workout import _normalize_answer
        options = q.get("options", [])
        correct_raw = str(q.get("answer", ""))
        correct_norm = _normalize_answer(correct_raw)
        if user_text.isdigit():
            n = int(user_text) - 1
            user_ans_norm = _normalize_answer(options[n]) if 0 <= n < len(options) else _normalize_answer(user_text)
        else:
            user_ans_norm = _normalize_answer(user_text)

        is_correct = user_ans_norm == correct_norm
        if is_correct:
            score += 1
            reply = f"✅ Верно!"
            if explanation:
                reply += f"\n💡 {explanation}"
        else:
            from bot.services.groq_client import ask_groq_text
            gpt_text = await ask_groq_text(
                "You are an English teacher. Explain in Russian (3-5 sentences) why the student's answer is wrong. "
                "Name the specific grammar rule, give the logic. No flattery. Plain text only.",
                f"Question: {q.get('sentence', '')}\nStudent: {user_text}\nCorrect: {correct_raw}\nTopic: {q.get('pattern', explanation)}"
            )
            reply = f"❌ Правильно: {correct_raw}\n\n{gpt_text}" if gpt_text else f"❌ Правильно: {correct_raw}"
            if explanation and not gpt_text:
                reply += f"\n💡 {explanation}"
    else:
        is_correct = False
        reply = f"✍️ Правильный ответ: {q.get('correct_en', q.get('answer', ''))}"

    await message.answer(reply)
    await state.update_data(cp_score=score)

    next_idx = idx + 1
    if next_idx < len(exercises):
        await _send_checkup_exercise(message, state, exercises, next_idx)
    else:
        total = len(exercises)
        await state.clear()
        pct = round(score / total * 100)
        verdict = "Всё верно 💪" if score == total else ("Неплохо" if pct >= 60 else "Надо повторить — эти паттерны всё ещё проблема")
        await message.answer(f"🏁 Результат: {score}/{total} ({pct}%)\n{verdict}")


# ─── Daily Challenge ───
class DailyChallengeStates(StatesGroup):
    answering = State()


@router.callback_query(F.data == "workout:daily_challenge")
async def cb_daily_challenge(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id

    # Check if challenge data is stored from scheduler
    challenge = getattr(callback.bot, "_daily_challenges", {}).get(user_id)
    if not challenge:
        await callback.message.answer(
            "✅ Задание дня уже выполнено!\n\nВозвращайся завтра за новым заданием."
        )
        return

    await state.set_state(DailyChallengeStates.answering)
    await state.update_data(
        challenge_answer=challenge["answer"],
        challenge_sentence=challenge["sentence"],
        challenge_options=challenge["options"],
        challenge_explanation=challenge.get("explanation", ""),
        challenge_rule=challenge.get("rule", ""),
    )

    # Remove "Ответить" button, show "Показать ответ"
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    skip_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Показать ответ", callback_data="challenge:skip")],
    ])
    await callback.message.edit_reply_markup(reply_markup=skip_kb)
    await callback.message.answer("Напиши номер или сам ответ:")


@router.message(DailyChallengeStates.answering)
async def cb_challenge_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    answer = data.get("challenge_answer", "")
    sentence = data.get("challenge_sentence", "")
    explanation = data.get("challenge_explanation", "")
    rule = data.get("challenge_rule", "")

    user_text = message.text.strip()
    options = data.get("challenge_options", [])

    from bot.handlers.workout import _normalize_answer

    # Map number to option
    if user_text.isdigit():
        n = int(user_text) - 1
        user_answer = options[n].lower() if 0 <= n < len(options) else user_text.lower()
    else:
        user_answer = user_text.lower()

    user_norm = _normalize_answer(user_answer)
    correct_norm = _normalize_answer(answer)
    is_correct = user_norm == correct_norm or correct_norm in user_norm or user_norm in correct_norm

    await state.clear()
    await _finish_challenge(message, is_correct, answer, explanation, rule, message.from_user.id)


@router.callback_query(F.data == "challenge:skip")
async def cb_challenge_skip(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    answer = data.get("challenge_answer", "")
    explanation = data.get("challenge_explanation", "")
    rule = data.get("challenge_rule", "")

    await state.clear()
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await _finish_challenge(callback.message, False, answer, explanation, rule, callback.from_user.id)


async def _finish_challenge(target, is_correct: bool, answer: str, explanation: str, rule: str, user_id: int):
    from datetime import date

    lines = []
    if is_correct:
        lines.append("✅ Правильно! +30 XP")
        xp = 30
    else:
        lines.append(f"❌ Ответ: {answer}")
        xp = 5

    if rule:
        lines.append(f"\n📐 {rule}")
    if explanation:
        lines.append(f"\n{explanation}")

    async with async_session() as session:
        await add_xp(session, user_id, xp, "daily_challenge")
        await session.commit()

    # Clear stored challenge so button shows "already done"
    challenges = getattr(target, "_daily_challenges", None)
    if challenges is None:
        # target is Message, try bot
        try:
            challenges = getattr(target.bot, "_daily_challenges", {})
        except Exception:
            challenges = {}
    challenges.pop(user_id, None)

    await target.answer("\n".join(lines))


# ─── Translation Workout ───
@router.callback_query(F.data == "workout:translation")
async def cb_workout_translation(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    from bot.handlers.workout import start_translation_workout
    await start_translation_workout(callback, state, callback.from_user.id)


# ─── Vocab reminder buttons ───
@router.callback_query(F.data == "vocab:start_review")
async def cb_vocab_start_review(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await _send_vocab_card(callback.message, state, callback.from_user.id)


@router.callback_query(F.data == "vocab:remind_later")
async def cb_vocab_remind_later(callback: CallbackQuery):
    await callback.answer("Хорошо, напомню позже")
    await callback.message.edit_reply_markup(reply_markup=None)


# ─── Vocab save from phrase of day ───
@router.callback_query(F.data == "vocab:phrase_save")
async def cb_phrase_vocab_save(callback: CallbackQuery):
    user_id = callback.from_user.id
    from bot.services.phrase_of_day import get_cached_phrase
    phrase = get_cached_phrase(user_id)

    if not phrase:
        await callback.answer("Фраза недоступна, перезапусти бот")
        return

    word = phrase.get("phrase", "")
    translation = phrase.get("translation", "")

    async with async_session() as session:
        result = await add_word(session, user_id, word, translation, "")

    if result:
        async with async_session() as session:
            await add_xp(session, user_id, XP_NEW_WORD, "word_added")
        await callback.answer(f"✅ '{word}' добавлено! +{XP_NEW_WORD} XP")
        await callback.message.edit_reply_markup(reply_markup=None)
    else:
        await callback.answer(f"'{word}' уже в словаре")


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
