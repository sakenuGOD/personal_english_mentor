from __future__ import annotations

import logging
import os
import tempfile

from aiogram import Router, F, Bot
from aiogram.types import Message

from bot.services.groq_client import transcribe_voice, ask_groq
from bot.utils.prompts import VOICE_ANALYSIS_SYSTEM

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot):
    """Handle voice messages in DM — pronunciation analysis."""
    await message.answer("🎤 Анализирую произношение...")

    file = await bot.get_file(message.voice.file_id)
    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    try:
        await bot.download_file(file.file_path, tmp.name)
        tmp.close()

        transcription = await transcribe_voice(tmp.name)
        if not transcription:
            await message.answer("⚠️ Не удалось распознать речь. Попробуй ещё раз.")
            return

        logger.info(f"Voice transcription: '{transcription}', sending for analysis...")
        result = await ask_groq(VOICE_ANALYSIS_SYSTEM, transcription)
        logger.info(f"Voice analysis result: {result}")
        if not result:
            await message.answer(
                f"🎤 Транскрипция: {transcription}\n\n"
                "⚠️ Не удалось проанализировать произношение."
            )
            return

        lines = [
            f"🎤 Ты сказал: \"{result.get('transcribed', transcription)}\"",
        ]

        intended = result.get("intended", "")
        if intended and intended != result.get("transcribed", ""):
            lines.append(f"💭 Имелось в виду: \"{intended}\"")

        score = result.get("score", 5)
        bar = "█" * score + "░" * (10 - score)
        lines.append(f"\n📊 {bar} {score}/10")

        issues = result.get("pronunciation_issues", [])
        if issues:
            lines.append("")
            for p in issues:
                word = p.get("word", "")
                sound = p.get("sound", "")
                said = p.get("said_like", "")
                should = p.get("should_be", "")
                lines.append(f"🔸 {word}: {said} → {should}")
                if sound:
                    lines.append(f"   🔊 Звук: {sound}")
                if p.get("tip"):
                    lines.append(f"   💡 {p['tip']}")
                lines.append("")

        tip = result.get("overall_tip", "")
        if tip:
            lines.append(f"💡 {tip}")

        await message.answer("\n".join(lines))

    finally:
        os.unlink(tmp.name)
