from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

from sqlalchemy import select, update

from bot.db.database import async_session
from bot.db.models import User, DailyMessageBuffer

logger = logging.getLogger(__name__)


async def scheduler_loop(bot):
    """Runs forever, fires scheduled tasks every 60 seconds."""
    logger.info("Scheduler started")
    tick = 0
    while True:
        try:
            await asyncio.sleep(60)
            tick += 1
            now = datetime.now(timezone.utc)
            await _check_phrase_of_day(bot, now)
            await _check_daily_challenge(bot, now)
            if now.weekday() == 6:
                await _check_weekly_insights(bot, now)
            # End-of-day checkup: per-user, fires 1h before their phrase-of-day digest
            await _check_daily_checkup(bot, now)
            # Vocab reminder — check every 30 minutes
            if tick % 30 == 0:
                await _check_vocab_reminder(bot)
        except Exception as e:
            logger.error(f"Scheduler error: {e}")


async def _check_phrase_of_day(bot, now: datetime):
    """Send phrase of the day to users whose time has come."""
    today = date.today()
    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                User.notifications == True,
            )
        )
        users = result.scalars().all()

    for user in users:
        try:
            # Skip if already sent today
            if user.phrase_last_sent and user.phrase_last_sent >= today:
                continue

            # Check if current UTC hour matches digest_time hour (simple check)
            digest_hour = user.digest_time.hour if user.digest_time else 9
            if now.hour != digest_hour:
                continue

            # Generate and send phrase
            from bot.services.phrase_of_day import generate_phrase_of_day, format_phrase_message, cache_phrase, phrase_keyboard
            phrase = await generate_phrase_of_day(user.topic_pack or "general")
            if not phrase:
                continue

            cache_phrase(user.id, phrase)
            text = format_phrase_message(phrase)
            await bot.send_message(chat_id=user.id, text=text, reply_markup=phrase_keyboard())

            # Mark as sent
            async with async_session() as session:
                await session.execute(
                    update(User).where(User.id == user.id).values(phrase_last_sent=today)
                )
                await session.commit()

            logger.info(f"Sent phrase of day to user {user.id}")

        except Exception as e:
            logger.warning(f"Failed to send phrase to user {user.id}: {e}")


async def _check_daily_challenge(bot, now: datetime):
    """Send daily challenge to users at their digest hour (1h after phrase of day)."""
    today = date.today()
    async with async_session() as session:
        result = await session.execute(select(User).where(User.notifications == True))
        users = result.scalars().all()

    for user in users:
        try:
            if user.challenge_last_sent and user.challenge_last_sent >= today:
                continue

            # Send 1 hour after phrase of day
            digest_hour = user.digest_time.hour if user.digest_time else 9
            challenge_hour = (digest_hour + 1) % 24
            if now.hour != challenge_hour:
                continue

            from bot.services.groq_client import ask_groq
            from bot.utils.prompts import DAILY_CHALLENGE_SYSTEM
            from bot.db.models import Error
            from sqlalchemy import func

            async with async_session() as session:
                top_cats = (await session.execute(
                    select(Error.category, func.count(Error.id))
                    .where(Error.user_id == user.id)
                    .group_by(Error.category)
                    .order_by(func.count(Error.id).desc())
                    .limit(3)
                )).all()

            weak_hint = ""
            if top_cats:
                cats = ", ".join(c for c, _ in top_cats)
                weak_hint = f"Focus on: {cats}"

            result = await ask_groq(DAILY_CHALLENGE_SYSTEM, weak_hint or "General grammar")
            if not result:
                continue

            sentence = result.get("sentence", "")
            options = result.get("options", [])
            answer = result.get("answer", "")
            rule_name = result.get("rule_name", "")

            if not sentence or not options or not answer:
                continue

            lines = ["🌅 Задание дня\n", sentence, ""]
            for i, opt in enumerate(options, 1):
                lines.append(f"  {i}. {opt}")
            lines.append("\n(напиши номер или ответ)")

            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Ответить", callback_data="workout:daily_challenge")],
            ])
            await bot.send_message(chat_id=user.id, text="\n".join(lines), reply_markup=kb)

            # Mark as sent today
            async with async_session() as session:
                await session.execute(
                    update(User).where(User.id == user.id).values(challenge_last_sent=today)
                )
                await session.commit()

            logger.info(f"Sent daily challenge to user {user.id}")

        except Exception as e:
            logger.warning(f"Daily challenge failed for user {user.id}: {e}")


async def _check_vocab_reminder(bot):
    """Send vocab review reminder if user has words due and hasn't been reminded in 8h."""
    from bot.services.vocabulary import get_words_for_review
    from bot.keyboards.inline import vocab_reminder_keyboard

    now = datetime.now(timezone.utc)
    min_interval_hours = 8
    cutoff = now.replace(tzinfo=None) - __import__("datetime").timedelta(hours=min_interval_hours)

    async with async_session() as session:
        result = await session.execute(select(User).where(User.notifications == True))
        users = result.scalars().all()

    for user in users:
        try:
            # Skip if reminded recently
            if user.vocab_reminded_at and user.vocab_reminded_at > cutoff:
                continue

            # Check if words are due
            async with async_session() as session:
                due_words = await get_words_for_review(session, user.id, limit=5)

            if not due_words:
                continue

            count = len(due_words)
            word_preview = ", ".join(f'"{w.word}"' for w in due_words[:3])
            text = (
                f"📚 Пора повторить слова!\n\n"
                f"У тебя {count} слов{'о' if count == 1 else 'а' if count < 5 else ''} ждут повторения:\n"
                f"{word_preview}{'...' if count > 3 else ''}\n\n"
                f"Проверим себя?"
            )

            from bot.keyboards.inline import vocab_reminder_keyboard
            await bot.send_message(chat_id=user.id, text=text, reply_markup=vocab_reminder_keyboard())

            # Update reminded_at
            async with async_session() as session:
                await session.execute(
                    update(User).where(User.id == user.id).values(vocab_reminded_at=now.replace(tzinfo=None))
                )
                await session.commit()

            logger.info(f"Sent vocab reminder to user {user.id} ({count} words due)")

        except Exception as e:
            logger.warning(f"Vocab reminder failed for user {user.id}: {e}")


async def _check_daily_checkup(bot, now: datetime):
    """Send end-of-day language checkup based on buffered messages.
    Fires at 20:58 UTC (= 23:58 MSK) — 1h before phrase-of-day at 09:00 UTC (= 12:00 MSK).
    Uses digest_hour to compute: checkup = digest_hour + 11 (mod 24) at minute 58.
    """
    from bot.services.groq_client import ask_groq
    from bot.utils.prompts import DAILY_CHECKUP_SYSTEM
    from sqlalchemy import delete
    import json

    today = date.today()

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.notifications == True)
        )
        users = result.scalars().all()

    for user in users:
        try:
            if user.checkup_last_sent and user.checkup_last_sent >= today:
                continue

            # Checkup fires 11 hours after digest (phrase) time → for digest=9 UTC → checkup=20 UTC = 23 MSK
            digest_hour = user.digest_time.hour if user.digest_time else 9
            checkup_hour = (digest_hour + 11) % 24
            if now.hour != checkup_hour or now.minute < 58:
                continue

            # Get today's buffered messages + errors from DB
            async with async_session() as session:
                buf_result = await session.execute(
                    select(DailyMessageBuffer)
                    .where(DailyMessageBuffer.user_id == user.id)
                    .order_by(DailyMessageBuffer.created_at)
                )
                messages = buf_result.scalars().all()

            if len(messages) < 3:
                async with async_session() as session:
                    await session.execute(
                        delete(DailyMessageBuffer).where(DailyMessageBuffer.user_id == user.id)
                    )
                    await session.commit()
                continue

            # ── Smart sampling: 15 msgs from each real-time window ──
            from bot.db.models import Error as ErrorModel
            from datetime import timedelta
            import random

            all_msgs = messages
            total = len(all_msgs)

            # Filter out very short messages (<5 words)
            meaningful = [m for m in all_msgs if len(m.text.split()) >= 5]
            if len(meaningful) < len(all_msgs) * 0.3:
                meaningful = all_msgs  # fallback

            # Split by real hour: morning 6-12, afternoon 12-18, evening 18-23, night 23-6
            def _time_window(m):
                h = m.created_at.hour
                if 6 <= h < 12: return 0
                if 12 <= h < 18: return 1
                if 18 <= h < 23: return 2
                return 3  # night 23-6

            windows = {0: [], 1: [], 2: [], 3: []}
            for m in meaningful:
                windows[_time_window(m)].append(m)

            sample = []
            if total <= 60:
                sample = meaningful
            else:
                for w in windows.values():
                    if w:
                        picked = random.sample(w, min(15, len(w))) if len(w) > 15 else w
                        sample.extend(picked)
                sample.sort(key=lambda m: m.created_at)

            # ── All today's errors from DB (compact, covers everything LT caught) ──
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            async with async_session() as session:
                db_errors = (await session.execute(
                    select(ErrorModel)
                    .where(ErrorModel.user_id == user.id, ErrorModel.created_at >= today_start)
                    .order_by(ErrorModel.created_at)
                )).scalars().all()

            # Build GPT input
            import json as _json
            sample_texts = "\n".join(f"- {m.text}" for m in sample)
            errors_data = [
                {
                    "original": e.original_text,
                    "corrected": e.corrected_text,
                    "category": e.category,
                    "explanation": e.short_explanation or "",
                }
                for e in db_errors
            ]
            gpt_input = _json.dumps({
                "message_sample": sample_texts,
                "total_messages_today": total,
                "detected_errors": errors_data,
            }, ensure_ascii=False)

            gpt = await ask_groq(DAILY_CHECKUP_SYSTEM, gpt_input)
            if not gpt:
                continue

            sep = "═" * 28
            top_patterns = gpt.get("top_patterns", [])
            overall = gpt.get("overall_assessment", {})

            def _split_page(lines):
                """Split lines into <=3400 char chunks."""
                text = "\n".join(lines)
                if len(text) <= 3400:
                    return [text]
                chunks, chunk = [], []
                for line in lines:
                    if len("\n".join(chunk)) + len(line) + 1 > 3400:
                        chunks.append("\n".join(chunk))
                        chunk = [line]
                    else:
                        chunk.append(line)
                if chunk:
                    chunks.append("\n".join(chunk))
                return chunks

            final_pages = []

            # ── Page 1: Overall assessment ──
            p1 = [sep, "🌙 Чекап дня", ""]
            grade = gpt.get("overall_grade", "")
            if grade:
                p1.append(f"Оценка: {grade}")
            verdict = overall.get("verdict", "")
            if verdict:
                p1.append("")
                p1.append(verdict)

            comm = overall.get("communication_style", "")
            if comm:
                p1.append("")
                p1.append("🗣 Стиль общения:")
                p1.append(comm)

            variety = overall.get("construction_variety", "")
            if variety:
                p1.append("")
                p1.append("🔧 Конструкции:")
                p1.append(variety)

            resp_q = overall.get("response_quality", "")
            if resp_q:
                p1.append("")
                p1.append("💬 Качество ответов:")
                p1.append(resp_q)

            used = gpt.get("constructions_used", [])
            if used:
                p1.append("")
                p1.append(f"Использовал: {', '.join(used)}")

            strong = overall.get("strong_points", [])
            if strong:
                p1.append("")
                p1.append("💪 Хорошо:")
                for s in strong:
                    p1.append(f"  • {s}")

            missed = gpt.get("missed_opportunities", [])
            if missed:
                p1.append("")
                p1.append("💡 Можно было лучше:")
                for m in missed:
                    p1.append(f'\n«{m.get("user_wrote", "")}»')
                    p1.append(f'→ {m.get("would_be_better", "")}')
                    p1.append(f'({m.get("construction", "")} — {m.get("why", "")})')

            p1.append(sep)
            final_pages.extend(_split_page(p1))

            # ── One page per pattern ──
            for i, pat in enumerate(top_patterns, 1):
                pp = [sep, f"📌 Паттерн {i}/{len(top_patterns)}: {pat.get('pattern_name', '')}", ""]
                freq = pat.get("frequency", "")
                if freq:
                    pp.append(f"Встречается: {freq}")
                    pp.append("")
                desc = pat.get("description", "")
                if desc:
                    pp.append(desc)
                    pp.append("")
                examples = pat.get("examples", [])
                if examples:
                    pp.append("Примеры из твоих сообщений:")
                    for ex in examples:
                        pp.append(f"  • {ex}")
                pp.append(sep)
                final_pages.extend(_split_page(pp))

            # Store pages + errors in bot-level dicts keyed by user_id
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            if not hasattr(bot, "_checkup_pages"):
                bot._checkup_pages = {}
            if not hasattr(bot, "_checkup_patterns"):
                bot._checkup_patterns = {}
            bot._checkup_pages[user.id] = final_pages
            # Store top_patterns for practice button — GPT will drill these
            bot._checkup_patterns[user.id] = gpt.get("top_patterns", [])

            def checkup_kb(page, total):
                nav = []
                if page > 0:
                    nav.append(InlineKeyboardButton(text="◀️", callback_data=f"checkup:page:{page-1}"))
                if total > 1:
                    nav.append(InlineKeyboardButton(text=f"{page+1}/{total}", callback_data="noop"))
                if page < total - 1:
                    nav.append(InlineKeyboardButton(text="▶️", callback_data=f"checkup:page:{page+1}"))
                rows = [nav] if nav else []
                rows.append([InlineKeyboardButton(text="📝 Проработать ошибки", callback_data="checkup:practice")])
                return InlineKeyboardMarkup(inline_keyboard=rows)

            await bot.send_message(
                chat_id=user.id,
                text=final_pages[0],
                reply_markup=checkup_kb(0, len(final_pages))
            )

            # Mark sent + clear buffer
            async with async_session() as session:
                await session.execute(
                    update(User).where(User.id == user.id).values(checkup_last_sent=today)
                )
                await session.execute(
                    delete(DailyMessageBuffer).where(DailyMessageBuffer.user_id == user.id)
                )
                await session.commit()

            logger.info(f"Sent daily checkup to user {user.id} ({len(texts)} messages analyzed)")

        except Exception as e:
            logger.warning(f"Daily checkup failed for user {user.id}: {e}")


async def _check_weekly_insights(bot, now: datetime):
    """Send weekly insights every Sunday."""
    today = date.today()
    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                User.notifications == True,
            )
        )
        users = result.scalars().all()

    for user in users:
        try:
            if user.weekly_last_sent and user.weekly_last_sent >= today:
                continue

            # Only send at digest hour
            digest_hour = user.digest_time.hour if user.digest_time else 21
            if now.hour != digest_hour:
                continue

            from bot.services.digest import generate_weekly_insights
            async with async_session() as session:
                text = await generate_weekly_insights(session, user.id)

            if not text:
                continue

            await bot.send_message(chat_id=user.id, text=text)

            async with async_session() as session:
                await session.execute(
                    update(User).where(User.id == user.id).values(weekly_last_sent=today)
                )
                await session.commit()

            logger.info(f"Sent weekly insights to user {user.id}")

        except Exception as e:
            logger.warning(f"Failed to send weekly insights to user {user.id}: {e}")
