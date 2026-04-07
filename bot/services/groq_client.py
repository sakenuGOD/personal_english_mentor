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


_MINI_CHECK_SYSTEM = (
    "You are an English grammar judge for a chat messenger context. "
    "Reply with ONLY the single word YES or NO — nothing else, no explanation. "
    "\n"
    "YES = the text has a REAL grammar error: wrong verb form, wrong tense, wrong word order, "
    "subject-verb disagreement, clearly wrong preposition, missing required article, "
    "stative verb in continuous, Russian calque that doesn't work in English. "
    "\n"
    "NO = text is correct English, even if informal/casual. "
    "Ignore: missing punctuation, missing capitalization, abbreviations (ur/gonna/wanna/lol/lmk), "
    "missing commas, informal phrasing, slang. "
    "Short casual phrases like 'I am fine thank you' or 'haha thats funny' = NO. "
    "\n"
    "Only YES for actual grammar errors a native speaker would NOT make."
)


async def ask_grammar_check(text: str) -> bool | None:
    """
    Ultra-cheap GPT grammar filter: returns True if errors found, False if clean, None on failure.
    Cost: ~$0.000015 per call (2-3 tokens output).
    Use as Layer 3 when pattern checker + LT both say clean.
    """
    try:
        c = _get_client()
        response = await c.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _MINI_CHECK_SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            max_tokens=3,
        )
        answer = (response.choices[0].message.content or "").strip().upper()
        if answer.startswith("YES"):
            return True
        if answer.startswith("NO"):
            return False
        return None  # unexpected answer
    except Exception as e:
        logger.warning(f"Mini grammar check failed: {e}")
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
