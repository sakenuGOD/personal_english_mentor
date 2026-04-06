from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PROXYAPI_KEY = os.getenv("PROXYAPI_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///english_buddy.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Allowed user IDs (empty = everyone allowed)
ALLOWED_USERS: set[int] = {5265189110}  # @narcolepsyy

OPENAI_BASE_URL = "https://api.proxyapi.ru/openai/v1"
OPENAI_MODEL = "gpt-4o-mini"
WHISPER_MODEL = "whisper-1"

# XP settings
XP_NO_ERROR = 10
XP_COMPLEX_NO_ERROR = 25
XP_ERROR = -5
XP_NEW_WORD = 15
XP_WORD_REMEMBERED = 10
XP_ROLEPLAY_DONE = 50
XP_DAILY_CHALLENGE = 30

LEVELS = [
    ("newbie", "🥉 Newbie", 0),
    ("explorer", "🥈 Explorer", 500),
    ("speaker", "🥇 Speaker", 2000),
    ("fluent", "💎 Fluent", 5000),
    ("native", "👑 Native", 15000),
]

LEITNER_INTERVALS = {
    1: 1,    # days
    2: 3,
    3: 7,
    4: 14,
    5: 30,
}
