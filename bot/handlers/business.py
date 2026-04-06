from __future__ import annotations

import logging
from collections import defaultdict

from aiogram import Router, F, Bot
from aiogram.types import Message, BusinessConnection, MessageReactionUpdated
from sqlalchemy import select, update

from bot.db.database import async_session
from bot.db.models import User
from bot.services.grammar import (
    check_grammar, save_error, save_message,
    format_chat_correction, format_detailed_correction,
)
from bot.services.local_grammar import has_errors as local_has_errors
from bot.services.gamification import add_xp, update_streak
from bot.handlers.commands import get_or_create_user
from bot.config import XP_NO_ERROR, XP_COMPLEX_NO_ERROR, XP_ERROR

router = Router()
logger = logging.getLogger(__name__)

# Cache recent messages: {(chat_id, message_id): {"text": ..., "user_id": ...}}
_msg_cache: dict[tuple, dict] = {}
MAX_CACHE = 500

# Short phrases that don't need checking
SKIP_PHRASES = {
    "ok", "okay", "yes", "no", "yeah", "yep", "nope", "sure", "thanks",
    "thank you", "bye", "hi", "hello", "hey", "lol", "haha", "nice",
    "cool", "great", "wow", "omg", "brb", "gtg", "idk", "tbh", "imo",
    "np", "ty", "yw", "gn", "gm", "wdym", "lmao", "fr", "nah",
}


async def _delete_business_msg(bot: Bot, business_connection_id: str, message_id: int):
    """Delete a message in business chat via raw API (Bot API 9.0 deleteBusinessMessages)."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as http:
            await http.post(
                f"https://api.telegram.org/bot{bot.token}/deleteBusinessMessages",
                json={
                    "business_connection_id": business_connection_id,
                    "message_ids": [message_id],
                },
            )
    except Exception as e:
        logger.warning(f"Failed to delete business message: {e}")


def _cache_message(chat_id: int, message_id: int, text: str, user_id: int):
    """Cache a message for reaction-based checking."""
    if len(_msg_cache) > MAX_CACHE:
        # Remove oldest entries
        keys = list(_msg_cache.keys())
        for k in keys[:MAX_CACHE // 2]:
            _msg_cache.pop(k, None)
    _msg_cache[(chat_id, message_id)] = {"text": text, "user_id": user_id}


@router.business_connection()
async def handle_business_connection(event: BusinessConnection):
    """Save business_connection_id when user connects the bot."""
    user_id = event.user.id
    await get_or_create_user(user_id, event.user.username, event.user.first_name)
    async with async_session() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(business_connection_id=event.id)
        )
        await session.commit()
    logger.info(f"Business connection from user {user_id}: {event.id}")


@router.business_message()
async def handle_business_message(message: Message, bot: Bot):
    """Process messages from business chats."""
    if not message.text:
        return

    text = message.text.strip()
    business_connection_id = message.business_connection_id

    if not business_connection_id:
        return

    # Only correct the bot owner's messages
    async with async_session() as session:
        owner_result = await session.execute(
            select(User).where(User.business_connection_id == business_connection_id)
        )
        owner = owner_result.scalar_one_or_none()

    if not owner or message.from_user.id != owner.id:
        return

    user_id = message.from_user.id

    # Cache message for reply-based checking
    _cache_message(message.chat.id, message.message_id, text, user_id)

    # If user replies "?" to their own message → full GPT check (grammar + naturalness)
    if text in ("?", "/check", "check") and message.reply_to_message:
        reply_text = message.reply_to_message.text
        if reply_text and message.reply_to_message.from_user and message.reply_to_message.from_user.id == user_id:
            logger.info(f"Reply check from user {user_id}")
            # Delete "?" immediately via deleteBusinessMessages (Bot API 9.0)
            await _delete_business_msg(bot, business_connection_id, message.message_id)
            # Get user mode
            async with async_session() as s:
                ur = await s.execute(select(User).where(User.id == user_id))
                u = ur.scalar_one_or_none()
            m = u.correction_mode if u else "balanced"
            await _full_check(reply_text, user_id, message.chat.id, m, bot,
                              message=message.reply_to_message,
                              business_connection_id=business_connection_id,
                              reaction_check=True)
            return

    # Skip short messages
    if len(text) < 3 or len(text.split()) < 3:
        return

    # Skip common short phrases
    if text.lower().strip("!?.,") in SKIP_PHRASES:
        return

    # Skip non-latin messages
    latin_chars = sum(1 for c in text if c.isalpha() and ord(c) < 128)
    alpha_chars = sum(1 for c in text if c.isalpha())
    if alpha_chars > 0 and latin_chars / alpha_chars < 0.5:
        return

    # Get user settings
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if not user:
        user = await get_or_create_user(user_id)
        async with async_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

    mode = user.correction_mode if user else "balanced"

    # === LOCAL CHECK (free) ===
    has_local = await local_has_errors(text)

    if not has_local:
        # LanguageTool says OK → no API call, just log
        async with async_session() as session:
            await update_streak(session, user_id)
            await save_message(session, user_id, message.chat.id, False, 0)
            await add_xp(session, user_id, XP_NO_ERROR, "message_no_error")
            await session.commit()
        return

    # === LOCAL FOUND ERRORS → send to GPT for detailed explanation ===
    await _full_check(text, user_id, message.chat.id, mode, bot, message, business_connection_id)


async def _full_check(
    text: str, user_id: int, chat_id: int, mode: str,
    bot: Bot, message: Message | None = None,
    business_connection_id: str | None = None,
    reaction_check: bool = False,
):
    """Full GPT check — called for errors or reaction-triggered checks."""
    result = await check_grammar(text, mode)
    logger.info(f"Grammar check: has_errors={result.get('has_errors') if result else None}")
    if result is None:
        return

    constructions = result.get("constructions", [])
    corrections = result.get("corrections", [])
    native_tip = result.get("native_tip")

    async with async_session() as session:
        await update_streak(session, user_id)

        # Track grammar constructions
        if constructions:
            from bot.db.models import GrammarUsage
            from datetime import datetime
            for c in constructions:
                existing = await session.execute(
                    select(GrammarUsage).where(
                        GrammarUsage.user_id == user_id,
                        GrammarUsage.construction == c,
                    )
                )
                gu = existing.scalar_one_or_none()
                if gu:
                    gu.times_used += 1
                    gu.last_used = datetime.utcnow()
                else:
                    session.add(GrammarUsage(
                        user_id=user_id,
                        construction=c,
                        times_used=1,
                        last_used=datetime.utcnow(),
                    ))

        if corrections:
            await save_message(session, user_id, chat_id, True, len(corrections))
            for c in corrections:
                await save_error(session, user_id, chat_id, c)
            await add_xp(session, user_id, XP_ERROR * len(corrections), "grammar_error")
        else:
            await save_message(session, user_id, chat_id, False, 0)
            is_complex = any(c in ["present_perfect", "past_perfect", "conditional_2",
                                    "conditional_3", "passive_voice"] for c in constructions)
            xp = XP_COMPLEX_NO_ERROR if is_complex else XP_NO_ERROR
            await add_xp(session, user_id, xp, "message_no_error")

        await session.commit()

    # Edit the original message with corrected version
    if mode != "silent" and corrections and message:
        corrected_full = result.get("corrected_full", "")
        if corrected_full and corrected_full.strip().lower() != text.strip().lower():
            try:
                await bot.edit_message_text(
                    text=corrected_full,
                    chat_id=chat_id,
                    message_id=message.message_id,
                    business_connection_id=business_connection_id,
                )
            except Exception as e:
                logger.warning(f"Failed to edit message: {e}")

    # Send detailed explanation to DM
    chat_name = f"@{message.chat.username}" if message and message.chat.username else str(chat_id)

    if corrections:
        detailed = format_detailed_correction(corrections, chat_name)
        try:
            await bot.send_message(chat_id=user_id, text=detailed)
        except Exception as e:
            logger.error(f"Failed to send DM correction: {e}")

    # Native tip (grammar ok but unnatural)
    if native_tip:
        try:
            sep = "=" * 30
            await bot.send_message(
                chat_id=user_id,
                text=f"{sep}\n"
                     f"Чат {chat_name}\n\n"
                     f"Так не говорят:\n\n"
                     f"  {text}\n"
                     f"  -> {native_tip}\n"
                     f"\n{sep}",
            )
        except Exception as e:
            logger.error(f"Failed to send native tip: {e}")

    # Reaction check: if no errors and no native tip
    if reaction_check and not corrections and not native_tip:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=f"Чат {chat_name}\n\n"
                     f'"{text}"\n\n'
                     f"Всё правильно, звучит естественно.",
            )
        except Exception as e:
            logger.error(f"Failed to send reaction result: {e}")


@router.message_reaction()
async def handle_reaction(event: MessageReactionUpdated, bot: Bot):
    """When user reacts to their OWN message → full GPT check."""
    logger.info(f"REACTION HANDLER: chat={event.chat.id} msg={event.message_id} user={event.user}")

    if not event.new_reaction:
        return
    if not event.user:
        return

    user_id = event.user.id
    chat_id = event.chat.id
    message_id = event.message_id

    # Check cache
    cached = _msg_cache.get((chat_id, message_id))
    if not cached:
        logger.info(f"Reaction: msg {message_id} not in cache")
        return

    # Only check own messages
    if cached["user_id"] != user_id:
        logger.info(f"Reaction: not owner's message")
        return

    text = cached["text"]
    if len(text) < 3 or len(text.split()) < 3:
        return

    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    mode = user.correction_mode if user else "balanced"

    logger.info(f"Reaction check from user {user_id}")
    await _full_check(text, user_id, chat_id, mode, bot, reaction_check=True)


