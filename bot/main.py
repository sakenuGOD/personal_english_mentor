from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import BOT_TOKEN
from bot.db.database import init_db
from bot.handlers import (
    commands, business, check, howtosay, words, meaning,
    roleplay, voice, ai_chat, workout, callbacks, translate, inline_query,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting English Buddy Bot...")

    await init_db()
    logger.info("Database initialized")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=None),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Register routers (order matters for FSM)
    dp.include_router(business.router)
    dp.include_router(callbacks.router)
    dp.include_router(commands.router)
    dp.include_router(check.router)
    dp.include_router(howtosay.router)
    dp.include_router(words.router)
    dp.include_router(meaning.router)
    dp.include_router(roleplay.router)
    dp.include_router(voice.router)
    dp.include_router(ai_chat.router)
    dp.include_router(workout.router)
    dp.include_router(translate.router)
    dp.include_router(inline_query.router)

    # Debug: log ALL raw updates
    from aiogram.types import Update
    @dp.update.outer_middleware()
    async def log_all_updates(handler, event: Update, data):
        fields = event.model_dump(exclude_none=True)
        fields.pop("update_id", None)
        logger.info(f"UPDATE keys={list(fields.keys())}")
        if "message_reaction" in fields:
            logger.info(f"REACTION DATA: {fields['message_reaction']}")
        return await handler(event, data)

    logger.info("Bot is running!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(
        bot,
        allowed_updates=[
            "message",
            "callback_query",
            "inline_query",
            "business_connection",
            "business_message",
            "edited_business_message",
            "message_reaction",
        ],
    )


if __name__ == "__main__":
    asyncio.run(main())
