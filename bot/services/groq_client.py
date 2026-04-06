from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from bot.config import PROXYAPI_KEY, OPENAI_BASE_URL, OPENAI_MODEL, WHISPER_MODEL

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=PROXYAPI_KEY, base_url=OPENAI_BASE_URL)
    return _client


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
