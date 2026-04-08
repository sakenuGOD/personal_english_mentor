"""Free LLM clients: Groq (primary) → Gemini (fallback).
Used ONLY for business chat grammar checking to save paid API tokens.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime

import aiohttp

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = "gemini-2.0-flash-lite"

# Track which provider is exhausted today
_exhausted: dict[str, str] = {}  # {"groq": "2026-04-08", "gemini": "2026-04-08"}


def _is_exhausted(provider: str) -> bool:
    return _exhausted.get(provider) == str(date.today())


def _mark_exhausted(provider: str):
    _exhausted[provider] = str(date.today())
    logger.warning(f"Free LLM provider '{provider}' exhausted for today")


async def _ask_groq_free(system_prompt: str, user_message: str) -> dict | None:
    """Call Groq free tier."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GROQ_BASE, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 429:
                    _mark_exhausted("groq")
                    return None
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"Groq free error {resp.status}: {body[:200]}")
                    if resp.status in (401, 403):
                        _mark_exhausted("groq")
                    return None
                data = await resp.json()
                text = data["choices"][0]["message"]["content"]
                return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Groq free: invalid JSON")
        return None
    except Exception as e:
        logger.error(f"Groq free error: {e}")
        return None


async def _ask_gemini_free(system_prompt: str, user_message: str) -> dict | None:
    """Call Gemini free tier."""
    url = f"{GEMINI_BASE}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_message}"}]},
        ],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2000,
            "responseMimeType": "application/json",
        },
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 429:
                    _mark_exhausted("gemini")
                    return None
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(f"Gemini free error {resp.status}: {body[:200]}")
                    if resp.status in (401, 403):
                        _mark_exhausted("gemini")
                    return None
                data = await resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Gemini free: invalid JSON")
        return None
    except Exception as e:
        logger.error(f"Gemini free error: {e}")
        return None


async def ask_free_llm(system_prompt: str, user_message: str) -> dict | None:
    """Try Groq free → Gemini free → return None (caller should use paid API)."""
    if not _is_exhausted("groq"):
        result = await _ask_groq_free(system_prompt, user_message)
        if result is not None:
            return result

    if not _is_exhausted("gemini"):
        result = await _ask_gemini_free(system_prompt, user_message)
        if result is not None:
            return result

    # Both exhausted
    return None


def both_exhausted() -> bool:
    """Check if both free providers are exhausted today."""
    return _is_exhausted("groq") and _is_exhausted("gemini")
