from __future__ import annotations

import logging
import re
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


# ═══════════════════════════════════════════════
#  SMART PATTERN CHECKER
#  Catches errors LanguageTool consistently misses
# ═══════════════════════════════════════════════

# Common irregular verb forms: {base: (past, past_participle)}
_IRREGULARS = {
    "be": ("was", "been"), "begin": ("began", "begun"), "break": ("broke", "broken"),
    "bring": ("brought", "brought"), "build": ("built", "built"), "buy": ("bought", "bought"),
    "catch": ("caught", "caught"), "choose": ("chose", "chosen"), "come": ("came", "come"),
    "cut": ("cut", "cut"), "do": ("did", "done"), "draw": ("drew", "drawn"),
    "drink": ("drank", "drunk"), "drive": ("drove", "driven"), "eat": ("ate", "eaten"),
    "fall": ("fell", "fallen"), "feel": ("felt", "felt"), "find": ("found", "found"),
    "fly": ("flew", "flown"), "forget": ("forgot", "forgotten"), "get": ("got", "gotten"),
    "give": ("gave", "given"), "go": ("went", "gone"), "grow": ("grew", "grown"),
    "have": ("had", "had"), "hear": ("heard", "heard"), "hold": ("held", "held"),
    "keep": ("kept", "kept"), "know": ("knew", "known"), "leave": ("left", "left"),
    "let": ("let", "let"), "lose": ("lost", "lost"), "make": ("made", "made"),
    "meet": ("met", "met"), "pay": ("paid", "paid"), "put": ("put", "put"),
    "read": ("read", "read"), "ride": ("rode", "ridden"), "ring": ("rang", "rung"),
    "rise": ("rose", "risen"), "run": ("ran", "run"), "say": ("said", "said"),
    "see": ("saw", "seen"), "sell": ("sold", "sold"), "send": ("sent", "sent"),
    "set": ("set", "set"), "show": ("showed", "shown"), "sing": ("sang", "sung"),
    "sit": ("sat", "sat"), "sleep": ("slept", "slept"), "speak": ("spoke", "spoken"),
    "spend": ("spent", "spent"), "stand": ("stood", "stood"), "swim": ("swam", "swum"),
    "take": ("took", "taken"), "teach": ("taught", "taught"), "tell": ("told", "told"),
    "think": ("thought", "thought"), "throw": ("threw", "thrown"),
    "understand": ("understood", "understood"), "wake": ("woke", "woken"),
    "wear": ("wore", "worn"), "win": ("won", "won"), "write": ("wrote", "written"),
}

# Common regular verbs (not in irregulars list)
_REGULAR_VERBS = {
    "work", "play", "walk", "talk", "call", "look", "move", "live", "love",
    "like", "want", "need", "help", "try", "use", "ask", "turn", "start",
    "stop", "open", "close", "wait", "watch", "listen", "learn", "study",
    "teach", "cook", "clean", "wash", "fix", "change", "check", "pick",
    "pull", "push", "drop", "fill", "kill", "plan", "rain", "save",
    "stay", "step", "pass", "miss", "wish", "hope", "enjoy", "finish",
    "happen", "follow", "create", "develop", "manage", "provide", "offer",
    "consider", "include", "allow", "believe", "expect", "decide", "require",
    "produce", "suggest", "explain", "travel", "dance", "smile", "laugh",
    "cry", "jump", "climb", "type", "code", "text", "chat", "post",
    "share", "search", "browse", "stream", "download", "upload",
}

# Build reverse lookups
_BASE_FORMS = set(_IRREGULARS.keys()) | _REGULAR_VERBS
_PAST_FORMS = {v[0] for v in _IRREGULARS.values()} | {v[1] for v in _IRREGULARS.values()}
_PAST_TO_BASE = {}
for base, (past, pp) in _IRREGULARS.items():
    _PAST_TO_BASE[past] = base
    _PAST_TO_BASE[pp] = base

# Words that look like base verbs but aren't (adjectives, nouns, etc.)
_NOT_VERBS = {
    "there", "here", "able", "away", "back", "out", "up", "down", "over", "off",
    "together", "apart", "through", "around", "along", "about", "across",
    "sure", "ready", "happy", "sorry", "glad", "afraid", "available",
    "possible", "important", "necessary", "right", "wrong", "true", "false",
    "open", "closed", "free", "busy", "full", "empty", "new", "old",
    "good", "bad", "fine", "okay", "great", "nice", "cool", "real",
    "involved", "married", "born", "interested", "excited", "tired",
    "bored", "confused", "surprised", "worried", "scared", "pleased",
    "not", "also", "just", "still", "even", "only", "really", "very",
    "quite", "always", "never", "often", "already", "enough", "much",
    "more", "less", "lot", "bit", "well", "far", "long", "fast",
}


def _is_base_verb(word: str) -> bool:
    """Check if word looks like a base form verb (not -ing, not -ed, not adjective)."""
    w = word.lower()
    if w in _NOT_VERBS:
        return False
    if w.endswith("ing") or w.endswith("ed") or w.endswith("ly"):
        return False
    if len(w) < 2:
        return False
    # Known base form
    if w in _BASE_FORMS:
        return True
    # Looks like a verb (not ending in typical noun/adj suffixes)
    if w.endswith(("tion", "sion", "ment", "ness", "ity", "ous", "ive", "ful", "less", "able", "ible")):
        return False
    return True


def _check_patterns(text: str) -> list[str]:
    """Check text for grammar patterns LanguageTool misses. Returns list of error descriptions."""
    words = text.lower().split()
    errors = []

    for i in range(len(words) - 1):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else ""
        nxt2 = words[i + 2] if i + 2 < len(words) else ""
        prev = words[i - 1] if i > 0 else ""

        # ── Pattern 1: "been + base verb" (should be been + V-ing) ──
        # "had been wait", "has been work", "have been go"
        if w == "been" and nxt and _is_base_verb(nxt) and not nxt.endswith("ing"):
            if nxt not in {"to", "a", "an", "the", "my", "his", "her", "their", "its", "our", "your"}:
                if nxt in _BASE_FORMS or (not nxt.endswith(("tion", "sion", "ment", "ness"))):
                    errors.append(f"been {nxt} → been {nxt}ing")

        # ── Pattern 2: "did + past tense" (should be did + base form) ──
        # "did went", "did saw", "didn't came"
        if w in ("did", "didn't", "didnt") and nxt in _PAST_TO_BASE:
            base = _PAST_TO_BASE[nxt]
            if nxt != base:  # past form differs from base
                errors.append(f"did {nxt} → did {base}")

        # ── Pattern 3: "to + past form" (should be to + base form) ──
        # "to went", "to bought", "to spoke"
        if w == "to" and nxt in _PAST_TO_BASE:
            base = _PAST_TO_BASE[nxt]
            if nxt != base and base != nxt:
                errors.append(f"to {nxt} → to {base}")

        # ── Pattern 4: "am/is/are + base verb" (should be V-ing for continuous) ──
        # "I am work", "she is go", "they are play"
        if w in ("am", "is", "are") and nxt and _is_base_verb(nxt) and not nxt.endswith("ing"):
            # Exclude: "is not", "is a/the", "is going to", etc.
            if nxt not in {"not", "a", "an", "the", "my", "his", "her", "their", "its",
                          "our", "your", "this", "that", "no", "so", "too", "being",
                          "gonna", "going", "about", "supposed", "allowed", "likely",
                          "used", "able", "such", "what", "how", "why", "where", "when"}:
                if nxt in _BASE_FORMS:
                    errors.append(f"{w} {nxt} → {w} {nxt}ing")

        # ── Pattern 5: "have/has + base verb" (should be have + V3) ──
        # "I have go", "she has see", "we have take"
        if w in ("have", "has", "haven't", "hasn't", "havent", "hasnt") and nxt in _BASE_FORMS:
            if nxt in _IRREGULARS:
                past, pp = _IRREGULARS[nxt]
                if nxt != pp:  # base differs from past participle
                    errors.append(f"{w} {nxt} → {w} {pp}")
            elif nxt in _REGULAR_VERBS:
                errors.append(f"{w} {nxt} → {w} {nxt}ed")

        # ── Pattern 6: "was/were + base verb" (should be V-ing or V3) ──
        # "I was go", "they were play"
        if w in ("was", "were") and nxt and _is_base_verb(nxt) and not nxt.endswith("ing"):
            if nxt not in {"not", "a", "an", "the", "my", "his", "her", "their", "its",
                          "our", "your", "this", "that", "no", "so", "too", "being",
                          "gonna", "going", "about", "supposed", "able", "just",
                          "never", "always", "also", "still", "even", "only",
                          "such", "what", "how", "why", "where", "when"}:
                if nxt in _BASE_FORMS:
                    errors.append(f"{w} {nxt} → {w} {nxt}ing")

        # ── Pattern 7: double past "did + V-ed" ──
        # "did worked", "did played", "didn't watched"
        if w in ("did", "didn't", "didnt") and nxt and nxt.endswith("ed") and len(nxt) > 3:
            base = nxt[:-2] if not nxt.endswith("ied") else nxt[:-3] + "y"
            errors.append(f"did {nxt} → did {base}")

        # ── Pattern 8: "more + -er" or "most + -est" ──
        # "more bigger", "most fastest"
        if w == "more" and nxt and nxt.endswith("er") and len(nxt) > 3:
            errors.append(f"more {nxt} → {nxt} (без more)")
        if w == "most" and nxt and nxt.endswith("est") and len(nxt) > 4:
            errors.append(f"most {nxt} → {nxt} (без most)")

        # ── Pattern 9: "he/she/it + base verb" (should be V+s in present) ──
        # "she go", "he work", "it make" — but only if clearly present tense context
        if w in ("he", "she", "it") and nxt in _BASE_FORMS:
            # Only flag if NOT after modal/auxiliary verbs
            modal_words = {"will", "would", "can", "could", "should", "might", "may",
                          "did", "didn't", "didnt", "to", "does", "doesn't", "doesnt",
                          "shall", "must", "let", "lets", "if", "when", "that", "who",
                          "watch", "watched", "saw", "see", "heard", "hear",
                          "make", "made", "help", "helped"}
            if prev not in modal_words:
                errors.append(f"{w} {nxt} → {w} {nxt}s")

    return errors


# ═══════════════════════════════════════════════
#  LANGUAGETOOL API
# ═══════════════════════════════════════════════

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


# ═══════════════════════════════════════════════
#  COMBINED CHECKER
# ═══════════════════════════════════════════════

async def has_errors(text: str) -> bool:
    """Quick check: does the text have grammar errors?
    Uses LanguageTool API + local pattern matching.
    Returns True if API failed (fallback to GPT)."""

    # 1. Smart pattern check (instant, free)
    pattern_errors = _check_patterns(text)
    if pattern_errors:
        logger.info(f"Pattern checker found: {pattern_errors}")
        return True

    # 2. LanguageTool API
    errors = await check_local(text)
    if errors is None:
        # API failed → send to GPT to be safe
        return True
    return len(errors) > 0
