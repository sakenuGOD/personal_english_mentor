from __future__ import annotations

import json
import logging
from datetime import date

import aiohttp
from openai import AsyncOpenAI

from bot.config import PROXYAPI_KEY, OPENAI_BASE_URL, OPENAI_MODEL, WHISPER_MODEL

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

# In-memory daily token counter: {"YYYY-MM-DD": {"in": N, "out": N, "calls": N}}
_token_log: dict[str, dict] = {}


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=PROXYAPI_KEY, base_url=OPENAI_BASE_URL)
    return _client


def _track(usage) -> None:
    """Record token usage from an API response."""
    if not usage:
        return
    today = str(date.today())
    if today not in _token_log:
        _token_log[today] = {"in": 0, "out": 0, "calls": 0}
    _token_log[today]["in"] += getattr(usage, "prompt_tokens", 0)
    _token_log[today]["out"] += getattr(usage, "completion_tokens", 0)
    _token_log[today]["calls"] += 1


def get_usage_stats() -> dict:
    """Return today's, yesterday's and all-time usage."""
    from datetime import timedelta
    today = str(date.today())
    yesterday = str(date.today() - timedelta(days=1))
    total_all: dict = {"in": 0, "out": 0, "calls": 0}
    for day_stats in _token_log.values():
        total_all["in"] += day_stats["in"]
        total_all["out"] += day_stats["out"]
        total_all["calls"] += day_stats["calls"]
    return {
        "today": _token_log.get(today, {"in": 0, "out": 0, "calls": 0}),
        "yesterday": _token_log.get(yesterday, {"in": 0, "out": 0, "calls": 0}),
        "total_all": total_all,
        "days_tracked": max(len(_token_log), 1),
    }


async def get_api_balance() -> str | None:
    """Fetch ProxyAPI account balance."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.proxyapi.ru/proxyapi/balance",
                headers={"Authorization": f"Bearer {PROXYAPI_KEY}"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    balance = data.get("balance") or data.get("amount") or data.get("credits")
                    if balance is not None:
                        return str(balance)
                return None
    except Exception as e:
        logger.warning(f"Balance check failed: {e}")
        return None


async def ask_groq(system_prompt: str, user_message: str, **kwargs) -> dict | None:
    """Chat completion returning parsed JSON."""
    try:
        c = _get_client()
        response = await c.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=2000,
        )
        _track(response.usage)
        text = response.choices[0].message.content
        if not text:
            return None
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON: {text[:300]}")
        return None
    except Exception as e:
        logger.error(f"API error: {e}")
        return None


async def ask_groq_text(system_prompt: str, user_message: str, **kwargs) -> str | None:
    """Chat completion returning raw text."""
    try:
        c = _get_client()
        response = await c.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        _track(response.usage)
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"API error: {e}")
        return None


async def ask_groq_chat(messages: list[dict], **kwargs) -> dict | None:
    """Multi-turn chat returning parsed JSON."""
    try:
        c = _get_client()
        response = await c.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=2000,
        )
        _track(response.usage)
        text = response.choices[0].message.content
        if not text:
            return None
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON chat: {text[:300]}")
        return None
    except Exception as e:
        logger.error(f"API error: {e}")
        return None


async def ask_groq_text_chat(messages: list[dict], **kwargs) -> str | None:
    """Multi-turn chat returning raw text."""
    try:
        c = _get_client()
        response = await c.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=2000,
        )
        _track(response.usage)
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"API error: {e}")
        return None


async def transcribe_voice(file_path: str, **kwargs) -> str | None:
    """Transcribe voice using Whisper."""
    try:
        c = _get_client()
        with open(file_path, "rb") as f:
            response = await c.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=f,
                language="en",
            )
        return response.text
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return None


def is_rate_limited(result) -> bool:
    return False
