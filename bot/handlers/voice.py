from __future__ import annotations

import logging
import os
import tempfile

from aiogram import Router, F, Bot
from aiogram.types import Message, Voice

from bot.services.groq_client import transcribe_voice, ask_groq
from bot.utils.prompts import MEANING_SYSTEM

router = Router()
logger = logging.getLogger(__name__)


async def _process_voice(message: Message, bot: Bot, voice: Voice):
    """Shared logic: download voice, transcribe, analyze, reply."""
    await message.answer("🎤 Слушаю...")

    file = await bot.get_file(voice.file_id)
    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    try:
        await bot.download_file(file.file_path, tmp.name)
        tmp.close()

        transcription = await transcribe_voice(tmp.name)
        if not transcription:
            await message.answer("⚠️ Не удалось распознать речь. Попробуй ещё раз.")
            return

        result = await ask_groq(MEANING_SYSTEM, transcription)

        lines = [f"🎤 Транскрипция:\n\"{transcription}\"", ""]

        if not result:
            await message.answer("\n".join(lines) + "\n⚠️ Не удалось проанализировать.")
            return

        translation = result.get("translation", "")
        if translation:
            lines.append(f"📝 Перевод: {translation}")
            lines.append("")

        meaning = result.get("meaning")
        if meaning:
            lines.append(f"🧠 {meaning}")
            lines.append("")

        tone = result.get("tone", "")
        if tone:
            lines.append(f"🎭 Тон: {tone}")
            lines.append("")

        word_breakdown = result.get("word_breakdown", [])
        if word_breakdown:
            lines.append("🔤 Разбор:")
            for wb in word_breakdown:
                word = wb.get("word", "")
                wmean = wb.get("meaning", "")
                is_slang = wb.get("is_slang", False)
                note = wb.get("note")
                slang_tag = " [сленг]" if is_slang else ""
                lines.append(f"  • {word}{slang_tag} — {wmean}")
                if note:
                    lines.append(f"    ↳ {note}")
            lines.append("")

        replies = result.get("how_to_reply", [])
        if replies:
            lines.append("💡 Как ответить:")
            for r in replies[:3]:
                lines.append(f"  • {r}")

        await message.answer("\n".join(lines))

    finally:
        os.unlink(tmp.name)


@router.message(F.reply_to_message.voice)
async def handle_reply_to_voice(message: Message, bot: Bot):
    """User replied to someone's voice message — transcribe and analyze it."""
    await _process_voice(message, bot, message.reply_to_message.voice)


@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot):
    """Handle own voice messages — transcribe, translate, explain."""
    await _process_voice(message, bot, message.voice)
