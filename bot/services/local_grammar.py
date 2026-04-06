from __future__ import annotations

import logging
import aiohttp

logger = logging.getLogger(__name__)

LANGUAGETOOL_URL = "https://api.languagetool.org/v2/check"

# Skip these rules in casual chat
SKIP_RULES = {
    "UPPERCASE_SENTENCE_START", "WHITESPACE_RULE",
    "COMMA_PARENTHESIS_WHITESPACE", "EN_QUOTES",
    "DOUBLE_PUNCTUATION", "SENTENCE_WHITESPACE",
}
SKIP_CATEGORIES = {"TYPOGRAPHY", "CASING"}


async def check_local(text: str) -> list[dict] | None:
    """Check text via LanguageTool public API. Returns list of errors, or None if API failed."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                LANGUAGETOOL_URL,
                data={"text": text, "language": "en-US"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"LanguageTool API returned {resp.status}")
                    return None
                data = await resp.json()
    except Exception as e:
        logger.warning(f"LanguageTool API error: {e}")
        return None

    errors = []
    for m in data.get("matches", []):
        rule_id = m.get("rule", {}).get("id", "")
        category_id = m.get("rule", {}).get("category", {}).get("id", "")

        if rule_id in SKIP_RULES:
            continue
        if category_id in SKIP_CATEGORIES:
            continue

        replacements = [r["value"] for r in m.get("replacements", [])[:3]]
        errors.append({
            "offset": m.get("offset", 0),
            "length": m.get("length", 0),
            "original": text[m.get("offset", 0):m.get("offset", 0) + m.get("length", 0)],
            "replacements": replacements,
            "rule": rule_id,
            "message": m.get("message", ""),
        })
    return errors


async def has_errors(text: str) -> bool:
    """Quick check: does the text have grammar errors? Returns True if API failed (fallback to GPT)."""
    errors = await check_local(text)
    if errors is None:
        # API failed → send to GPT to be safe
        return True
    return len(errors) > 0
