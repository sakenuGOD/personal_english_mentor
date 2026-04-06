from __future__ import annotations

import logging

import os
import tempfile

from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.services.groq_client import ask_groq_chat, ask_groq, transcribe_voice
from bot.utils.prompts import ROLEPLAY_SYSTEM, ROLEPLAY_START, ROLEPLAY_FINISH_SYSTEM
from bot.keyboards.inline import roleplay_scenarios_keyboard, roleplay_active_keyboard
from bot.db.database import async_session
from bot.db.models import RoleplaySession
from bot.services.gamification import add_xp
from bot.config import XP_ROLEPLAY_DONE

router = Router()
logger = logging.getLogger(__name__)


class RoleplayStates(StatesGroup):
    in_roleplay = State()
    waiting_custom = State()


async def show_roleplay_menu(target, state: FSMContext):
    """Show roleplay menu — called from Progress."""
    await state.clear()
    await target.answer(
        "🎭 Выбери сценарий для диалога:",
        reply_markup=roleplay_scenarios_keyboard(),
    )


async def begin_roleplay(message_or_callback, state: FSMContext, scenario: str):
    """Start a roleplay session."""
    start_prompt = ROLEPLAY_START.get(scenario, "Start a casual English conversation.")

    messages = [
        {"role": "system", "content": ROLEPLAY_SYSTEM},
        {"role": "user", "content": f"Scenario: {scenario}. {start_prompt}"},
    ]

    result = await ask_groq_chat(messages)
    if not result:
        if hasattr(message_or_callback, "answer"):
            await message_or_callback.answer("⚠️ Сервис временно недоступен.")
        return

    reply = result.get("reply", "Hello! Let's begin.")
    messages.append({"role": "assistant", "content": str(result)})

    await state.set_state(RoleplayStates.in_roleplay)
    await state.update_data(
        scenario=scenario,
        chat_messages=messages,
        user_messages=[],
    )

    scenario_names = {
        "job_interview": "💼 Job Interview",
        "restaurant": "🍽 Restaurant",
        "hotel_checkin": "🏨 Hotel Check-in",
        "tech_support": "📞 Tech Support",
        "smalltalk": "🤝 Smalltalk",
        "return_item": "🛒 Return Item",
        "airport": "✈️ Airport",
        "doctor_visit": "🏥 Doctor Visit",
        "salary_talk": "💰 Salary Talk",
        "project_defense": "🎓 Project Defense",
    }
    name = scenario_names.get(scenario, scenario)

    text = f"🎭 {name}\n\n{reply}"
    vocab_tip = result.get("vocabulary_tip")
    if vocab_tip:
        text += f"\n\n💡 Полезная фраза: {vocab_tip}"

    if hasattr(message_or_callback, "answer"):
        await message_or_callback.answer(text, reply_markup=roleplay_active_keyboard())
    else:
        await message_or_callback.message.edit_text(text, reply_markup=roleplay_active_keyboard())


@router.message(RoleplayStates.waiting_custom)
async def custom_roleplay(message: Message, state: FSMContext):
    if not message.text:
        return
    scenario = message.text.strip()
    # Use custom text as start prompt
    from bot.utils.prompts import ROLEPLAY_SYSTEM
    messages_list = [
        {"role": "system", "content": ROLEPLAY_SYSTEM},
        {"role": "user", "content": f"Custom scenario: {scenario}. Start the roleplay based on this situation. You play the other person."},
    ]
    result = await ask_groq_chat(messages_list)
    if not result:
        await message.answer("⚠️ Сервис временно недоступен.")
        await state.clear()
        return

    reply = result.get("reply", "Let's begin!")
    messages_list.append({"role": "assistant", "content": str(result)})

    await state.set_state(RoleplayStates.in_roleplay)
    await state.update_data(
        scenario="custom",
        chat_messages=messages_list,
        user_messages=[],
    )

    text = f"🎭 {scenario}\n\n{reply}"
    vocab_tip = result.get("vocabulary_tip")
    if vocab_tip:
        text += f"\n\n💡 {vocab_tip}"
    await message.answer(text, reply_markup=roleplay_active_keyboard())


@router.message(RoleplayStates.in_roleplay, F.voice)
async def roleplay_turn_voice(message: Message, state: FSMContext, bot: Bot):
    """Handle voice messages in roleplay — transcribe and process."""
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
        await message.answer("⚠️ Не удалось распознать речь. Попробуй ещё раз.")
        return

    await _roleplay_process(message, state, transcription, is_voice=True)


@router.message(RoleplayStates.in_roleplay)
async def roleplay_turn(message: Message, state: FSMContext):
    if not message.text:
        return
    await _roleplay_process(message, state, message.text)


async def _roleplay_process(message: Message, state: FSMContext, user_text: str, is_voice: bool = False):
    data = await state.get_data()
    chat_messages = data.get("chat_messages", [])
    user_messages = data.get("user_messages", [])

    chat_messages.append({"role": "user", "content": user_text})
    user_messages.append(user_text)

    result = await ask_groq_chat(chat_messages)
    if not result:
        await message.answer("⚠️ Не удалось получить ответ. Попробуй ещё раз.")
        return

    reply = result.get("reply", "")
    corrections = result.get("corrections", [])
    vocab_tip = result.get("vocabulary_tip")
    helped = result.get("helped_with_russian")

    chat_messages.append({"role": "assistant", "content": str(result)})
    await state.update_data(chat_messages=chat_messages, user_messages=user_messages)

    lines = []
    if is_voice:
        lines.append(f"🎤 {user_text}\n")
    lines.append(reply)

    if helped:
        lines.append(f"\n💡 Ты мог сказать: {helped}")

    if corrections:
        lines.append("\n📝 Ошибки:")
        for c in corrections:
            lines.append(f"  ❌ {c.get('original', '')} → ✅ {c.get('corrected', '')}")
            if c.get("tip"):
                lines.append(f"     💡 {c['tip']}")

    if vocab_tip:
        lines.append(f"\n💡 {vocab_tip}")

    await message.answer("\n".join(lines), reply_markup=roleplay_active_keyboard())


async def finish_roleplay(callback_or_message, state: FSMContext):
    """End roleplay and give evaluation."""
    data = await state.get_data()
    user_messages = data.get("user_messages", [])
    chat_messages = data.get("chat_messages", [])
    scenario = data.get("scenario", "")

    if not user_messages:
        if hasattr(callback_or_message, "answer"):
            await callback_or_message.answer("Диалог пуст, нечего оценивать.")
        await state.clear()
        return

    # Get message target (for sending messages, not callback toasts)
    from aiogram.types import CallbackQuery as CQ
    if isinstance(callback_or_message, CQ):
        target = callback_or_message.message
    else:
        target = callback_or_message

    # Build full conversation with both sides
    conv_lines = []
    for msg in chat_messages:
        if msg["role"] == "system":
            continue
        role = "Bot" if msg["role"] == "assistant" else "User"
        # For assistant messages, extract just the reply from JSON
        if role == "Bot":
            try:
                import json
                parsed = json.loads(msg["content"]) if msg["content"].startswith("{") else None
                text = parsed.get("reply", msg["content"]) if parsed else msg["content"]
            except Exception:
                text = msg["content"]
        else:
            text = msg["content"]
        conv_lines.append(f"{role}: {text}")

    conversation = "\n".join(conv_lines)

    await target.answer("🔍 Анализирую диалог...")

    result = await ask_groq(
        ROLEPLAY_FINISH_SYSTEM,
        f"Scenario: {scenario}\n\nFull conversation:\n{conversation}",
    )

    if not result:
        await target.answer("⚠️ Не удалось получить оценку.")
        await state.clear()
        return

    grade = result.get("grade", "?")
    strengths = result.get("strengths", [])
    weaknesses = result.get("weaknesses", [])
    phrases = result.get("suggested_phrases", [])
    comment = result.get("overall_comment", "")
    message_analysis = result.get("message_analysis", [])

    lines = [f"🏁 Оценка: {grade}\n"]

    # Per-message analysis
    if message_analysis:
        lines.append("📝 Разбор по сообщениям:\n")
        for i, ma in enumerate(message_analysis, 1):
            said = ma.get("user_said", "")
            lines.append(f"  {i}. \"{said}\"")
            errors = ma.get("errors")
            better = ma.get("better")
            note = ma.get("note")
            if errors:
                lines.append(f"     ❌ {errors}")
            if better:
                lines.append(f"     ✅ {better}")
            if note:
                lines.append(f"     💬 {note}")
            if not errors and not better and not note:
                lines.append(f"     ✅ Всё ок")
            lines.append("")

    if strengths:
        lines.append("💪 Сильные стороны:")
        for s in strengths:
            lines.append(f"  • {s}")
        lines.append("")

    if weaknesses:
        lines.append("📝 Над чем поработать:")
        for w in weaknesses:
            lines.append(f"  • {w}")
        lines.append("")

    if phrases:
        lines.append("💡 Фразы для этого сценария:")
        for p in phrases:
            lines.append(f"  • {p}")
        lines.append("")

    if comment:
        lines.append(f"📊 {comment}")

    # Save session and give XP
    user_id = callback_or_message.from_user.id
    async with async_session() as session:
        rp = RoleplaySession(
            user_id=user_id,
            scenario=scenario,
            messages={"user_messages": user_messages},
            grade=grade,
            feedback=comment,
        )
        session.add(rp)
        await session.commit()
        await add_xp(session, user_id, XP_ROLEPLAY_DONE, "roleplay_completed")

    await state.clear()

    text = "\n".join(lines)
    # Split if exceeds Telegram limit
    if len(text) <= 4096:
        await target.answer(text)
    else:
        # Send in chunks at line breaks
        chunks = []
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > 4000:
                chunks.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line
        if current:
            chunks.append(current)
        for chunk in chunks:
            await target.answer(chunk)
