from __future__ import annotations

import logging
import os
import tempfile

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from bot.db.database import async_session
from bot.db.models import Error
from bot.services.groq_client import ask_groq, ask_groq_text, transcribe_voice
from bot.utils.prompts import WORKOUT_SYSTEM
from bot.services.stats import get_category_name

router = Router()
logger = logging.getLogger(__name__)

# ─── Level test prompts (long, kept here) ───

LEVEL_TEST_GRAMMAR = """Generate a grammar test with 8 questions of increasing difficulty.
Each question tests a specific grammar point at a specific CEFR level.

Rules:
- Questions MUST get progressively harder
- Each question targets ONE grammar concept
- Include the CEFR level being tested
- Options must be plausible (not obviously wrong)

Respond ONLY in valid JSON:
{
  "tasks": [
    {
      "level": "A1",
      "skill": "grammar",
      "topic": "to be",
      "sentence": "She ___ a teacher.",
      "options": ["is", "are", "am", "be"],
      "answer": "is",
      "explanation": "She — 3-е лицо, значит is"
    }
  ]
}

Distribution: 2×A1-A2, 2×A2-B1, 2×B1-B2, 2×B2-C1 (progressively harder grammar).
Make questions that ACTUALLY test understanding, not trivial ones."""

LEVEL_TEST_VOCAB = """Generate a vocabulary test with 6 questions of increasing difficulty.
Test word meanings, collocations, and nuanced usage.

Respond ONLY in valid JSON:
{
  "tasks": [
    {
      "level": "A2",
      "skill": "vocabulary",
      "topic": "word meaning",
      "sentence": "Choose the word that means 'to start a journey': embark / embrace / emerge / employ",
      "options": ["embark", "embrace", "emerge", "employ"],
      "answer": "embark",
      "explanation": "embark = начать путешествие, отправиться"
    }
  ]
}

Distribution: 1×A2, 1×B1, 2×B2, 2×C1. Higher levels should test nuances and collocations."""

LEVEL_TEST_READING = """Generate a reading comprehension section.
Write a short text (8-10 sentences, B1-B2 level) and 3 questions about it.

The text should be interesting — a real-world topic (science, culture, technology).

Respond ONLY in valid JSON:
{
  "text": "The full text to read...",
  "tasks": [
    {
      "level": "B1",
      "skill": "reading",
      "topic": "comprehension",
      "sentence": "According to the text, what is...?",
      "options": ["option1", "option2", "option3", "option4"],
      "answer": "option1",
      "explanation": "В тексте сказано что..."
    }
  ]
}"""

LEVEL_TEST_WRITING = """You are evaluating a student's English writing.
The student was given a topic and wrote a response.

Evaluate: grammar accuracy, vocabulary range, coherence, complexity.

Respond ONLY in valid JSON:
{
  "grammar_score": 1-10,
  "vocabulary_score": 1-10,
  "coherence_score": 1-10,
  "complexity_score": 1-10,
  "estimated_level": "A1/A2/B1/B2/C1/C2",
  "errors": [
    {"error": "what's wrong", "fix": "how to fix", "type": "grammar/vocabulary/style"}
  ],
  "feedback": "Краткий отзыв на русском — что хорошо, что подтянуть"
}"""

LEVEL_TEST_SPEAKING = """You are evaluating a student's spoken English (transcribed from voice).
The student was given a question and answered by voice. You see the transcription.

Evaluate: grammar accuracy, vocabulary range, sentence complexity, fluency (can they form full sentences?).
Be honest — if the answer is short or broken, say so.

Respond ONLY in valid JSON:
{
  "grammar_score": 1-10,
  "vocabulary_score": 1-10,
  "fluency_score": 1-10,
  "complexity_score": 1-10,
  "estimated_level": "A1/A2/B1/B2/C1/C2",
  "errors": [
    {"error": "what's wrong", "fix": "how to fix", "type": "grammar/vocabulary/fluency"}
  ],
  "feedback": "Краткий отзыв на русском — как строит предложения, какие конструкции использует, что подтянуть"
}"""

SPEAKING_QUESTIONS = [
    "Describe your typical morning. What do you usually do after you wake up?",
    "Tell me about your favorite hobby. Why do you enjoy it?",
    "What would you do if you won a million dollars?",
    "Describe a person you admire. Why do you look up to them?",
    "What are the pros and cons of living in a big city?",
]

LEVEL_FINAL_SYSTEM = """Based on all test phases, determine the student's English level.

You receive scores from: Grammar test, Vocabulary test, Reading comprehension, Writing evaluation, Speaking evaluation.

Give an HONEST, detailed assessment. Don't inflate the level.

Respond ONLY in valid JSON:
{
  "level": "A1/A2/B1/B2/C1/C2",
  "confidence": "high/medium/low",
  "breakdown": {
    "grammar": "A1-C2 + краткий комментарий",
    "vocabulary": "A1-C2 + комментарий",
    "reading": "A1-C2 + комментарий",
    "writing": "A1-C2 + комментарий",
    "speaking": "A1-C2 + комментарий (based on sentence structure and vocabulary in transcribed speech)"
  },
  "summary": "3-4 предложения: общая оценка, главные плюсы и минусы",
  "action_plan": ["конкретное действие 1", "действие 2", "действие 3"]
}"""


class WorkoutStates(StatesGroup):
    config_count = State()
    config_hints = State()
    answering = State()
    level_grammar = State()
    level_vocab = State()
    level_reading = State()
    level_writing = State()
    level_speaking = State()
    translation_waiting = State()


# ═══════════════════════════════════════════
#  ERROR WORKOUT (тест по ошибкам)
# ═══════════════════════════════════════════

async def _get_error_summary(user_id: int) -> str | None:
    async with async_session() as session:
        errors = (
            await session.execute(
                select(Error.original_text, Error.corrected_text, Error.category, func.count(Error.id).label("cnt"))
                .where(Error.user_id == user_id)
                .group_by(Error.original_text, Error.corrected_text, Error.category)
                .order_by(func.count(Error.id).desc())
                .limit(15)
            )
        ).all()
    if not errors:
        return None
    return "\n".join(f"- \"{o}\" → \"{c}\" ({cat}, ×{n})" for o, c, cat, n in errors)


async def start_workout(callback_or_message, state: FSMContext, user_id: int):
    """Show workout config — how many questions, with/without hints."""
    target = callback_or_message.message if isinstance(callback_or_message, CallbackQuery) else callback_or_message

    error_summary = await _get_error_summary(user_id)
    if not error_summary:
        await target.answer("✅ Нет ошибок для проработки.")
        return

    await state.set_state(WorkoutStates.config_count)
    await state.update_data(workout_user_id=user_id)

    from bot.keyboards.inline import workout_count_keyboard
    await target.answer(
        "🎯 Тест по твоим ошибкам\n\n📊 Сколько вопросов?",
        reply_markup=workout_count_keyboard(),
    )


async def _generate_and_start_workout(target, state: FSMContext, user_id: int, count: int, hints: bool):
    """Actually generate and start the workout after config."""
    error_summary = await _get_error_summary(user_id)
    if not error_summary:
        await target.answer("✅ Нет ошибок для проработки.")
        await state.clear()
        return

    await target.answer("⏳ Генерирую упражнения...")
    hint_instruction = "Include hints for each task." if hints else "Do NOT include hints."
    result = await ask_groq(
        WORKOUT_SYSTEM,
        f"Student's errors:\n{error_summary}\n\nGenerate exactly {count} tasks. {hint_instruction}",
    )

    if not result or not result.get("tasks"):
        await target.answer("⚠️ Не удалось сгенерировать.")
        await state.clear()
        return

    tasks = result["tasks"][:count]
    if not hints:
        for t in tasks:
            t.pop("hint", None)

    await state.set_state(WorkoutStates.answering)
    await state.update_data(tasks=tasks, current=0, correct=0, total=len(tasks))

    text = f"🎯 {result.get('title', 'Проработка ошибок')}\n\n"
    text += _format_task(tasks[0], 1, len(tasks))

    from bot.keyboards.inline import workout_skip_keyboard
    await target.answer(text, reply_markup=workout_skip_keyboard())


def _format_task(task: dict, num: int, total: int) -> str:
    task_type = task.get("type", "fill_blank")
    sentence = task.get("sentence", "")
    labels = {"fill_blank": "Заполни пропуск", "correct_sentence": "Исправь ошибку", "choose_right": "Выбери правильный"}
    lines = [f"📌 {num}/{total} — {labels.get(task_type, task_type)}", f"\n  {sentence}"]
    hint = task.get("hint", "")
    if hint:
        lines.append(f"\n💡 {hint}")
    return "\n".join(lines)


@router.message(WorkoutStates.answering)
async def process_workout_answer(message: Message, state: FSMContext):
    if not message.text:
        return
    data = await state.get_data()
    tasks, current, correct, total = data["tasks"], data["current"], data["correct"], data["total"]
    if current >= len(tasks):
        await state.clear()
        return

    task = tasks[current]
    is_correct = message.text.strip().lower() == task.get("answer", "").strip().lower()
    if is_correct:
        correct += 1
        text = "✅ Правильно!"
    else:
        text = f"❌ Ответ: {task.get('answer', '')}"
        if task.get("related_error"):
            text += f"\n   📎 {task['related_error']}"

    next_idx = current + 1
    await state.update_data(current=next_idx, correct=correct)

    if next_idx >= total:
        text += _finish_text(correct, total)
        from bot.keyboards.inline import workout_done_keyboard
        await message.answer(text, reply_markup=workout_done_keyboard())
        await state.clear()
    else:
        text += "\n\n" + _format_task(tasks[next_idx], next_idx + 1, total)
        from bot.keyboards.inline import workout_skip_keyboard
        await message.answer(text, reply_markup=workout_skip_keyboard())


# ═══════════════════════════════════════════
#  GENERAL WORKOUT (общая тренировка)
# ═══════════════════════════════════════════

GENERAL_WORKOUT_SYSTEM = """You are an English teacher creating a general practice exercise.
Create exercises covering common grammar topics: tenses, articles, prepositions, conditionals, passive voice, etc.

Rules:
- Instructions in Russian, exercises in English
- Use ты, concise
- Mix difficulty levels (some easy, some hard)
- Cover different grammar topics in each exercise

Respond ONLY in valid JSON:
{
  "title": "Short title in Russian",
  "tasks": [
    {
      "type": "fill_blank",
      "sentence": "I ___ (go) to the store yesterday.",
      "answer": "went",
      "hint": "Past Simple — действие в прошлом с yesterday",
      "related_error": "Past Simple vs Present Perfect"
    }
  ],
  "summary": "1-2 sentences in Russian about what this targets"
}

Types: fill_blank, correct_sentence, choose_right."""


async def start_general_workout(callback_or_message, state: FSMContext, user_id: int):
    """Start general workout — not based on errors."""
    target = callback_or_message.message if isinstance(callback_or_message, CallbackQuery) else callback_or_message

    await state.set_state(WorkoutStates.config_count)
    await state.update_data(workout_user_id=user_id, workout_type="general")

    from bot.keyboards.inline import workout_count_keyboard
    await target.answer(
        "🎯 Общая тренировка\n\n📊 Сколько вопросов?",
        reply_markup=workout_count_keyboard(),
    )


async def _generate_and_start_general(target, state: FSMContext, count: int, hints: bool):
    """Generate general workout."""
    await target.answer("⏳ Генерирую упражнения...")
    hint_instruction = "Include hints for each task." if hints else "Do NOT include hints."
    result = await ask_groq(
        GENERAL_WORKOUT_SYSTEM,
        f"Generate exactly {count} tasks covering different grammar topics. {hint_instruction}",
    )

    if not result or not result.get("tasks"):
        await target.answer("⚠️ Не удалось сгенерировать.")
        await state.clear()
        return

    tasks = result["tasks"][:count]
    if not hints:
        for t in tasks:
            t.pop("hint", None)

    await state.set_state(WorkoutStates.answering)
    await state.update_data(tasks=tasks, current=0, correct=0, total=len(tasks))

    text = f"🎯 {result.get('title', 'Общая тренировка')}\n\n"
    text += _format_task(tasks[0], 1, len(tasks))

    from bot.keyboards.inline import workout_skip_keyboard
    await target.answer(text, reply_markup=workout_skip_keyboard())


# ═══════════════════════════════════════════
#  LEVEL TEST (тест на уровень — 5 этапов)
# ═══════════════════════════════════════════

async def start_level_test(callback_or_message, state: FSMContext, user_id: int):
    target = callback_or_message.message if isinstance(callback_or_message, CallbackQuery) else callback_or_message

    await target.answer(
        "📋 Тест на уровень английского\n\n"
        "5 этапов:\n"
        "1️⃣ Грамматика (8 вопросов)\n"
        "2️⃣ Лексика (6 вопросов)\n"
        "3️⃣ Чтение (текст + 3 вопроса)\n"
        "4️⃣ Письмо (напиши текст)\n"
        "5️⃣ Говорение (запиши голосовое)\n\n"
        "⏳ Генерирую грамматический тест..."
    )

    result = await ask_groq(LEVEL_TEST_GRAMMAR, "Generate grammar test")
    if not result or not result.get("tasks"):
        await target.answer("⚠️ Не удалось сгенерировать тест.")
        return

    tasks = result["tasks"]
    await state.set_state(WorkoutStates.level_grammar)
    await state.update_data(
        grammar_tasks=tasks, current=0, grammar_correct=0,
        grammar_answers=[], vocab_answers=[], reading_answers=[],
        writing_result=None,
    )

    text = "1️⃣ ГРАММАТИКА\n\n"
    text += _format_level_q(tasks[0], 1, len(tasks))

    from bot.keyboards.inline import workout_skip_keyboard
    await target.answer(text, reply_markup=workout_skip_keyboard())


def _format_level_q(task: dict, num: int, total: int) -> str:
    sentence = task.get("sentence", "")
    level = task.get("level", "")
    options = task.get("options", [])
    topic = task.get("topic", "")

    lines = [f"📌 {num}/{total} [{level}] {topic}", f"\n{sentence}"]
    if options:
        lines.append("")
        for i, opt in enumerate(options, 1):
            lines.append(f"  {i}. {opt}")
        lines.append("\n(номер или ответ)")
    return "\n".join(lines)


async def _process_level_answer(message: Message, state: FSMContext, tasks_key: str, correct_key: str, answers_key: str):
    """Generic handler for level test phases."""
    data = await state.get_data()
    tasks = data.get(tasks_key, [])
    current = data.get("current", 0)
    correct = data.get(correct_key, 0)
    answers = data.get(answers_key, [])

    if current >= len(tasks):
        return True, data

    task = tasks[current]
    user_text = message.text.strip()
    user_answer = user_text.lower()

    # Handle numeric answers
    options = task.get("options", [])
    if options and user_text.isdigit():
        idx = int(user_text) - 1
        if 0 <= idx < len(options):
            user_answer = options[idx].lower()

    expected = task.get("answer", "").strip().lower()
    is_correct = user_answer == expected

    if is_correct:
        correct += 1
        text = "✅"
    else:
        text = f"❌ {task.get('answer', '')}"
        expl = task.get("explanation", "")
        if expl:
            text += f" — {expl}"

    answers.append({"level": task.get("level", ""), "correct": is_correct, "topic": task.get("topic", "")})
    next_idx = current + 1
    await state.update_data(current=next_idx, **{correct_key: correct, answers_key: answers})

    if next_idx >= len(tasks):
        await message.answer(f"{text}\n\n✅ Этап завершён: {correct}/{len(tasks)}")
        return True, await state.get_data()
    else:
        reply = f"{text}\n\n{_format_level_q(tasks[next_idx], next_idx + 1, len(tasks))}"
        from bot.keyboards.inline import workout_skip_keyboard
        await message.answer(reply, reply_markup=workout_skip_keyboard())
        return False, None


@router.message(WorkoutStates.level_grammar)
async def process_level_grammar(message: Message, state: FSMContext):
    if not message.text:
        return

    done, data = await _process_level_answer(message, state, "grammar_tasks", "grammar_correct", "grammar_answers")
    if not done:
        return

    # Start vocabulary phase
    await message.answer("⏳ Генерирую лексический тест...")
    result = await ask_groq(LEVEL_TEST_VOCAB, "Generate vocabulary test")

    if not result or not result.get("tasks"):
        await message.answer("⚠️ Не удалось сгенерировать. Пропускаю этап.")
        await _start_reading_phase(message, state)
        return

    tasks = result["tasks"]
    await state.set_state(WorkoutStates.level_vocab)
    await state.update_data(vocab_tasks=tasks, current=0, vocab_correct=0)

    text = "2️⃣ ЛЕКСИКА\n\n"
    text += _format_level_q(tasks[0], 1, len(tasks))
    from bot.keyboards.inline import workout_skip_keyboard
    await message.answer(text, reply_markup=workout_skip_keyboard())


@router.message(WorkoutStates.level_vocab)
async def process_level_vocab(message: Message, state: FSMContext):
    if not message.text:
        return

    done, data = await _process_level_answer(message, state, "vocab_tasks", "vocab_correct", "vocab_answers")
    if not done:
        return

    await _start_reading_phase(message, state)


async def _start_reading_phase(message: Message, state: FSMContext):
    await message.answer("⏳ Генерирую текст для чтения...")
    result = await ask_groq(LEVEL_TEST_READING, "Generate reading comprehension")

    if not result or not result.get("tasks"):
        await message.answer("⚠️ Пропускаю этап чтения.")
        await _start_writing_phase(message, state)
        return

    reading_text = result.get("text", "")
    tasks = result["tasks"]
    await state.set_state(WorkoutStates.level_reading)
    await state.update_data(reading_tasks=tasks, current=0, reading_correct=0)

    text = f"3️⃣ ЧТЕНИЕ\n\nПрочитай текст и ответь на вопросы:\n\n{reading_text}\n\n"
    text += _format_level_q(tasks[0], 1, len(tasks))
    from bot.keyboards.inline import workout_skip_keyboard
    await message.answer(text, reply_markup=workout_skip_keyboard())


@router.message(WorkoutStates.level_reading)
async def process_level_reading(message: Message, state: FSMContext):
    if not message.text:
        return

    done, data = await _process_level_answer(message, state, "reading_tasks", "reading_correct", "reading_answers")
    if not done:
        return

    await _start_writing_phase(message, state)


async def _start_writing_phase(message: Message, state: FSMContext):
    await state.set_state(WorkoutStates.level_writing)
    await message.answer(
        "4️⃣ ПИСЬМО\n\n"
        "Напиши 5-10 предложений на тему:\n\n"
        "\"Describe your typical day. What do you usually do, "
        "and what did you do differently yesterday?\"\n\n"
        "Пиши на английском. Это последний этап."
    )


@router.message(WorkoutStates.level_writing)
async def process_level_writing(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Напиши текст на английском.")
        return

    await message.answer("🔍 Оцениваю текст...")

    # Evaluate writing
    writing_result = await ask_groq(
        LEVEL_TEST_WRITING,
        f"Topic: Describe your typical day\nStudent's text:\n{message.text}",
    )

    # Show writing feedback
    if writing_result:
        w = writing_result
        lines = [
            "📝 Оценка письма:",
            f"  Грамматика: {w.get('grammar_score', '?')}/10",
            f"  Лексика: {w.get('vocabulary_score', '?')}/10",
            f"  Связность: {w.get('coherence_score', '?')}/10",
            f"  Сложность: {w.get('complexity_score', '?')}/10",
        ]
        errors = w.get("errors", [])
        if errors:
            lines.append("\n❌ Ошибки:")
            for e in errors[:5]:
                lines.append(f"  • {e.get('error', '')} → {e.get('fix', '')}")
        feedback = w.get("feedback", "")
        if feedback:
            lines.append(f"\n💬 {feedback}")
        await message.answer("\n".join(lines))

    await state.update_data(writing_result=writing_result)
    await _start_speaking_phase(message, state)


async def _start_speaking_phase(message: Message, state: FSMContext):
    """Start speaking phase — ask a question, user records voice."""
    import random
    question = random.choice(SPEAKING_QUESTIONS)
    await state.set_state(WorkoutStates.level_speaking)
    await state.update_data(speaking_question=question)
    await message.answer(
        "5️⃣ ГОВОРЕНИЕ\n\n"
        "Запиши голосовое сообщение, ответь на вопрос:\n\n"
        f"🎤 \"{question}\"\n\n"
        "Говори на английском. Постарайся составить полные предложения."
    )


@router.message(WorkoutStates.level_speaking, F.voice)
async def process_level_speaking_voice(message: Message, state: FSMContext, bot: Bot):
    """Process voice answer in level test."""
    await message.answer("🎤 Слушаю...")

    file = await bot.get_file(message.voice.file_id)
    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    try:
        await bot.download_file(file.file_path, tmp.name)
        tmp.close()
        transcription = await transcribe_voice(tmp.name)
    finally:
        os.unlink(tmp.name)

    if not transcription:
        await message.answer("⚠️ Не удалось распознать. Попробуй ещё раз или напиши текстом.")
        return

    await message.answer(f"🎤 \"{transcription}\"\n\n🔍 Оцениваю...")

    data = await state.get_data()
    question = data.get("speaking_question", "")

    speaking_result = await ask_groq(
        LEVEL_TEST_SPEAKING,
        f"Question: {question}\nStudent's spoken answer (transcription):\n{transcription}",
    )

    if speaking_result:
        s = speaking_result
        lines = [
            "🎤 Оценка говорения:",
            f"  Грамматика: {s.get('grammar_score', '?')}/10",
            f"  Лексика: {s.get('vocabulary_score', '?')}/10",
            f"  Беглость: {s.get('fluency_score', '?')}/10",
            f"  Сложность: {s.get('complexity_score', '?')}/10",
        ]
        errors = s.get("errors", [])
        if errors:
            lines.append("\n❌ Ошибки:")
            for e in errors[:5]:
                lines.append(f"  • {e.get('error', '')} → {e.get('fix', '')}")
        feedback = s.get("feedback", "")
        if feedback:
            lines.append(f"\n💬 {feedback}")
        await message.answer("\n".join(lines))

    await state.update_data(speaking_result=speaking_result)
    await _finish_level_test(message, state)


@router.message(WorkoutStates.level_speaking)
async def process_level_speaking_text(message: Message, state: FSMContext):
    """Fallback: accept text if user can't record voice."""
    if not message.text:
        await message.answer("Запиши голосовое или напиши текстом.")
        return

    await message.answer("🔍 Оцениваю...")

    data = await state.get_data()
    question = data.get("speaking_question", "")

    speaking_result = await ask_groq(
        LEVEL_TEST_SPEAKING,
        f"Question: {question}\nStudent's answer (text, not voice):\n{message.text}",
    )

    if speaking_result:
        s = speaking_result
        lines = [
            "📝 Оценка ответа (текстом):",
            f"  Грамматика: {s.get('grammar_score', '?')}/10",
            f"  Лексика: {s.get('vocabulary_score', '?')}/10",
            f"  Сложность: {s.get('complexity_score', '?')}/10",
        ]
        errors = s.get("errors", [])
        if errors:
            lines.append("\n❌ Ошибки:")
            for e in errors[:5]:
                lines.append(f"  • {e.get('error', '')} → {e.get('fix', '')}")
        feedback = s.get("feedback", "")
        if feedback:
            lines.append(f"\n💬 {feedback}")
        await message.answer("\n".join(lines))

    await state.update_data(speaking_result=speaking_result)
    await _finish_level_test(message, state)


async def _finish_level_test(message: Message, state: FSMContext):
    """Final level determination after all 5 phases."""
    data = await state.get_data()

    grammar_answers = data.get("grammar_answers", [])
    vocab_answers = data.get("vocab_answers", [])
    reading_answers = data.get("reading_answers", [])
    grammar_correct = data.get("grammar_correct", 0)
    vocab_correct = data.get("vocab_correct", 0)
    reading_correct = data.get("reading_correct", 0)
    grammar_total = len(data.get("grammar_tasks", []))
    vocab_total = len(data.get("vocab_tasks", []))
    reading_total = len(data.get("reading_tasks", []))
    writing_result = data.get("writing_result")
    speaking_result = data.get("speaking_result")

    await message.answer("📊 Подвожу итоги...")

    analysis_input = f"""Test results:
Grammar: {grammar_correct}/{grammar_total}
Wrong grammar topics: {', '.join(a['topic'] for a in grammar_answers if not a['correct'])}

Vocabulary: {vocab_correct}/{vocab_total}
Wrong vocab topics: {', '.join(a['topic'] for a in vocab_answers if not a['correct'])}

Reading: {reading_correct}/{reading_total}

Writing evaluation: {writing_result if writing_result else 'skipped'}

Speaking evaluation: {speaking_result if speaking_result else 'skipped'}"""

    final = await ask_groq(LEVEL_FINAL_SYSTEM, analysis_input)

    if final:
        level = final.get("level", "?")
        breakdown = final.get("breakdown", {})
        summary = final.get("summary", "")
        plan = final.get("action_plan", [])

        result_lines = [
            f"{'━' * 25}",
            f"📊 ТВОЙ УРОВЕНЬ: {level}",
            f"{'━' * 25}",
            "",
        ]

        if breakdown:
            result_lines.append("Детализация:")
            for skill, comment in breakdown.items():
                emoji = {"grammar": "📏", "vocabulary": "📚", "reading": "📖", "writing": "✏️", "speaking": "🎤"}.get(skill, "•")
                result_lines.append(f"  {emoji} {skill.title()}: {comment}")
            result_lines.append("")

        if summary:
            result_lines.append(f"💬 {summary}")
            result_lines.append("")

        if plan:
            result_lines.append("📌 Что делать:")
            for p in plan:
                result_lines.append(f"  • {p}")

        from bot.keyboards.inline import progress_keyboard
        await message.answer("\n".join(result_lines), reply_markup=progress_keyboard())
    else:
        score = f"Грамматика {grammar_correct}/{grammar_total}, Лексика {vocab_correct}/{vocab_total}, Чтение {reading_correct}/{reading_total}"
        await message.answer(f"Результаты: {score}\n\nНе удалось определить итоговый уровень.")

    await state.clear()


def _finish_text(correct: int, total: int) -> str:
    text = f"\n\n{'─' * 20}\n🏁 Результат: {correct}/{total}"
    if correct == total:
        text += "\n🔥 Всё верно!"
    elif correct >= total * 0.6:
        text += "\n👍 Неплохо."
    else:
        text += "\n💪 Нужно подтянуть."


# ═══════════════════════════════════════════
#  TRANSLATION WORKOUT (переведи фразу)
# ═══════════════════════════════════════════

async def start_translation_workout(callback_or_message, state: FSMContext, user_id: int):
    """Generate a Russian phrase and ask user to translate it."""
    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import TRANSLATION_CHALLENGE_SYSTEM
    from bot.db.models import User as UserModel
    from sqlalchemy import select as sa_select

    target = callback_or_message.message if isinstance(callback_or_message, CallbackQuery) else callback_or_message

    # Get user level
    async with async_session() as session:
        u = await session.execute(sa_select(UserModel).where(UserModel.id == user_id))
        user = u.scalar_one_or_none()
    level = user.level if user else "B1"

    # Get already used phrases from FSM
    data = await state.get_data()
    used = data.get("translation_used", [])

    await target.answer("⏳ Генерирую фразу...")
    avoid = f"Avoid these phrases: {used[-5:]}" if used else ""
    result = await ask_groq(
        TRANSLATION_CHALLENGE_SYSTEM,
        f"Level: {level}. {avoid}",
    )

    if not result or not result.get("russian"):
        await target.answer("⚠️ Не удалось сгенерировать фразу. Попробуй ещё раз.")
        return

    russian = result["russian"]
    context = result.get("context")

    used.append(russian)
    await state.set_state(WorkoutStates.translation_waiting)
    await state.update_data(translation_phrase=russian, translation_used=used)

    text = "🇷🇺→🇬🇧 Переведи на английский:\n\n"
    text += f'"{russian}"'
    if context:
        text += f"\n\n💬 Контекст: {context}"

    from bot.keyboards.inline import workout_skip_keyboard
    await target.answer(text, reply_markup=workout_skip_keyboard())


@router.message(WorkoutStates.translation_waiting)
async def process_translation_answer(message: Message, state: FSMContext):
    """Evaluate user's translation."""
    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import TRANSLATION_EVAL_SYSTEM
    from bot.keyboards.inline import translation_result_keyboard
    import json

    user_answer = message.text.strip()
    data = await state.get_data()
    russian = data.get("translation_phrase", "")

    await message.answer("⏳ Оцениваю...")

    payload = json.dumps({"russian": russian, "student": user_answer})
    result = await ask_groq(TRANSLATION_EVAL_SYSTEM, payload)

    if not result:
        await message.answer("⚠️ Не удалось оценить. Попробуй ещё раз.", reply_markup=translation_result_keyboard())
        await state.clear()
        return

    total = result.get("total", 0)
    reference = result.get("reference", "")
    perfect = result.get("perfect", [])
    improve = result.get("improve", [])
    verdict = result.get("verdict", "")

    # Score emoji
    if total >= 90:
        badge = "🔥"
    elif total >= 75:
        badge = "👍"
    elif total >= 60:
        badge = "📈"
    else:
        badge = "💪"

    lines = [
        f"{badge} Оценка: {total}/100",
        "",
        f"  Грамматика:    {result.get('grammar', 0)}/30",
        f"  Естественность: {result.get('naturalness', 0)}/35",
        f"  Лексика:       {result.get('vocabulary', 0)}/35",
    ]

    if reference:
        lines.append("")
        lines.append(f'📌 Эталон: "{reference}"')

    if perfect:
        lines.append("")
        lines.append("✅ Хорошо:")
        for p in perfect:
            lines.append(f"  • {p}")

    if improve:
        lines.append("")
        lines.append("💡 Можно лучше:")
        for imp in improve:
            lines.append(f"  • {imp}")

    if verdict:
        lines.append("")
        lines.append(verdict)

    await state.clear()
    await message.answer("\n".join(lines), reply_markup=translation_result_keyboard())
    return text
