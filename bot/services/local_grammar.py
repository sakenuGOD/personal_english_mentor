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
    # ── Chat-friendly: skip casing/style in casual messages ──
    "I_LOWERCASE",                    # "i" instead of "I" — normal in chat
    "MORFOLOGIK_RULE_EN_US",          # spell-check: too many false positives on slang/names
    "EN_CONTRACTION_SPELLING",        # "dont" vs "don't" — fine in chat
    "WORD_CONTAINS_UNDERSCORE",       # code/usernames
    "EN_UNPAIRED_BRACKETS",           # casual punctuation
    "EN_A_VS_AN",                     # too aggressive, often wrong on acronyms
    "ENGLISH_WORD_REPEAT_RULE",       # "very very" — intentional emphasis in chat
    "COMMA_COMPOUND_SENTENCE",        # comma before "and" — style, not grammar
    "COMMA_COMPOUND_SENTENCE_2",      # same
    "MISSING_COMMA_AFTER_INTRODUCTORY_PHRASE",  # style
    "INTERJECTIONS_PUNCTUATION",      # "haha" needs comma — no in chat
    "DASH_RULE",                      # em-dash style
    "POSSESSIVE_APOSTROPHE",          # "thats" vs "that's" — chat
    "IT_IS",                          # "its" vs "it's" — often intentional in chat
    "IT_IS_2",                        # same
    "YOUR_YOU_RE",                    # "ur" / "your" — chat abbreviation
    "THEIR_IS",                       # "there" vs "their" — often intentional
    "BEEN_PART_AGREEMENT",            # often wrong on chat fragments
}
# Also skip rules that just suggest alternative spellings / style choices
SKIP_RULE_PREFIXES = {"AI_", "MORFOLOGIK_", "CONFUSION_RULE"}
SKIP_CATEGORIES = {"TYPOGRAPHY", "CASING", "STYLE"}


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
    # ── Extended: commonly confused / missed irregular verbs ──
    "lay": ("laid", "laid"), "lie": ("lay", "lain"),
    "hang": ("hung", "hung"), "shine": ("shone", "shone"),
    "bite": ("bit", "bitten"), "hide": ("hid", "hidden"),
    "dig": ("dug", "dug"), "stick": ("stuck", "stuck"),
    "strike": ("struck", "struck"), "shake": ("shook", "shaken"),
    "freeze": ("froze", "frozen"), "steal": ("stole", "stolen"),
    "tear": ("tore", "torn"), "blow": ("blew", "blown"),
    "seek": ("sought", "sought"), "slide": ("slid", "slid"),
    "swing": ("swung", "swung"), "cling": ("clung", "clung"),
    "creep": ("crept", "crept"), "leap": ("leapt", "leapt"),
    "weave": ("wove", "woven"), "bind": ("bound", "bound"),
    "grind": ("ground", "ground"), "wind": ("wound", "wound"),
    "bear": ("bore", "borne"), "swear": ("swore", "sworn"),
    "arise": ("arose", "arisen"), "awake": ("awoke", "awoken"),
    "forgive": ("forgave", "forgiven"), "forbid": ("forbade", "forbidden"),
    "withdraw": ("withdrew", "withdrawn"), "overcome": ("overcame", "overcome"),
    "undertake": ("undertook", "undertaken"), "mistake": ("mistook", "mistaken"),
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
_V3_FORMS = {v[1] for v in _IRREGULARS.values()}  # past participles only
_PAST_TO_BASE = {}
for base, (past, pp) in _IRREGULARS.items():
    _PAST_TO_BASE[past] = base
    _PAST_TO_BASE[pp] = base

# Regular -ed forms that are V3 (past participle) — for "been waited" detection
_REGULAR_ED = {v + "ed" for v in _REGULAR_VERBS if not v.endswith("e")}
_REGULAR_ED |= {v + "d" for v in _REGULAR_VERBS if v.endswith("e")}
_REGULAR_ED |= {v[:-1] + "ied" for v in _REGULAR_VERBS if v.endswith("y") and len(v) > 1 and v[-2] not in "aeiou"}
_ALL_V3 = _V3_FORMS | _REGULAR_ED  # all past participle forms

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


_STATIVE_VERBS = {
    "know", "believe", "understand", "remember", "forget", "realize",
    "recognize", "suppose", "mean", "contain", "consist", "belong",
    "own", "possess", "owe", "deserve", "lack", "matter", "mind",
    "doubt", "deny", "agree", "disagree", "refuse", "prefer",
    "hate", "adore", "appreciate", "envy", "fear", "trust",
    "seem", "appear", "resemble", "depend", "measure", "weigh", "cost",
}

_DOUBLE_MODALS = {"can", "could", "will", "would", "shall", "should", "may", "might", "must"}

_ABSOLUTE_ADJECTIVES = {
    "unique", "perfect", "complete", "absolute", "total", "entire",
    "impossible", "infinite", "dead", "empty", "full", "pregnant",
    "unanimous", "universal", "supreme", "essential", "fatal",
    "identical", "opposite", "ultimate", "final", "eternal",
}

_WRONG_PREPOSITIONS = {
    "depend of": "depend on", "depend from": "depend on",
    "consist from": "consist of", "consist in": "consist of",
    "arrive to": "arrive at/in", "arrive at home": "arrive home",
    "married with": "married to",
    "interested for": "interested in",
    "listen the": "listen to the", "listen a": "listen to a",
    "discuss about": "discuss (without about)",
    "enter to": "enter (without to)", "enter into the": "enter the",
    "explain me": "explain to me",
    "apologize him": "apologize to him", "apologize her": "apologize to her",
}

# Collective nouns that are always plural in English
_ALWAYS_PLURAL_NOUNS = {"police", "people", "cattle", "clergy", "militia"}

# Uncountable nouns that ESL learners often pluralize
_UNCOUNTABLE_NOUNS = {
    "advice", "information", "furniture", "equipment", "luggage", "baggage",
    "knowledge", "research", "homework", "housework", "work", "traffic",
    "travel", "progress", "evidence", "news", "music", "weather",
    "money", "bread", "rice", "water", "milk", "coffee", "tea",
    "sugar", "salt", "flour", "butter", "meat", "fruit", "hair",
    "feedback", "software", "hardware", "data", "staff", "vocabulary",
    "grammar", "slang", "underwear", "clothing", "jewelry",
}

# Countries/cities that should NOT have "the"
_NO_ARTICLE_PLACES = {
    "france", "germany", "italy", "spain", "japan", "china", "russia",
    "brazil", "india", "canada", "australia", "mexico", "turkey",
    "egypt", "greece", "poland", "sweden", "norway", "finland",
    "denmark", "portugal", "austria", "belgium", "switzerland",
    "ireland", "scotland", "england", "korea", "vietnam", "thailand",
    "indonesia", "malaysia", "singapore", "israel", "iran", "iraq",
    "africa", "europe", "asia", "london", "paris", "berlin", "rome",
    "moscow", "tokyo", "beijing", "seoul", "bangkok", "sydney",
    "amsterdam", "prague", "vienna", "warsaw", "budapest", "lisbon",
}

# Common Russisms / false-friend patterns
_RUSSISMS = {
    "feel myself": "feel (без myself, если не буквально «ощупывать себя»)",
    "learn by heart": None,  # correct — exclude from false positives
    "say him": "tell him",
    "say her": "tell her",
    "say them": "tell them",
    "say me": "tell me",
    "propose to go": "suggest going",
    "make a photo": "take a photo",
    "make photos": "take photos",
    "make a picture": "take a picture",
    "learn him": "teach him",
    "learn her": "teach her",
    "learn them": "teach them",
    "became to": "began to / started to",
    "win money": None,  # actually fine
    "recipe of": "recipe for",
    "return back": "return (без back — return уже значит «вернуться»)",
}

# Indirect-question trigger words
_INDIRECT_Q_TRIGGERS = {"ask", "asked", "wonder", "wondered", "wondering",
                        "know", "knew", "understand", "understood", "explain",
                        "explained", "tell", "told", "remember", "forgot"}

# make/do collocations: things that should use DO (not make)
_DO_NOT_MAKE = {
    "homework", "housework", "exercise", "sport", "yoga", "business",
    "research", "work", "job", "task", "assignment", "shopping",
    "cleaning", "cooking", "washing", "ironing", "gardening",
    "damage", "harm", "good", "well", "badly", "effort", "your best",
    "a favour", "me a favour", "nothing", "something", "everything",
    "anything", "whatever", "the right thing", "the wrong thing",
}
# make/do: things that should use MAKE (not do)
_MAKE_NOT_DO = {
    "a mistake", "mistakes", "a decision", "decisions", "a choice",
    "a promise", "promises", "a suggestion", "suggestions", "a request",
    "an appointment", "appointments", "a reservation", "reservations",
    "progress", "an effort", "efforts", "money", "a profit",
    "a phone call", "a call", "a noise", "a sound", "a mess",
    "a difference", "sense", "an excuse", "excuses", "a joke",
    "jokes", "fun", "friends", "a friend",
}

# Redundant word pairs (tautologies)
_REDUNDANT_PAIRS = {
    "return back": "return",
    "repeat again": "repeat",
    "revert back": "revert",
    "refer back": "refer",
    "end result": "result",
    "future plans": "plans",
    "past history": "history",
    "added bonus": "bonus",
    "free gift": "gift",
    "new innovation": "innovation",
    "unexpected surprise": "surprise",
    "close proximity": "proximity",
    "advance planning": "planning",
    "basic fundamentals": "fundamentals",
    "final conclusion": "conclusion",
    "how long time": "how long",
    "very much hungry": "very hungry",
    "very much tired": "very tired",
    "very much busy": "very busy",
}

# "although/even though X but Y" — but is redundant after although
_ALTHOUGH_BUT = re.compile(
    r'\b(although|even though|though|whereas|while)\b.*?\bbut\b',
    re.IGNORECASE
)

# "in + day_of_week" → "on + day_of_week"
_DAYS_OF_WEEK = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}

# Months for "in 15 March" → "on 15 March" / "on March 15"
_MONTHS = {"january", "february", "march", "april", "may", "june",
           "july", "august", "september", "october", "november", "december"}

# "I am agree/hungry/ready/..." — adjective used with "am" missing "feeling/getting"
_AM_ADJECTIVE_ERRORS = {
    "agree": "I agree (без am — agree — глагол, не прилагательное)",
    "disagree": "I disagree",
    "look": None,  # "I am look" caught by Pattern 4
}

# told + that (missing object: "she told that" → "she told me/him/us that")
_TELL_TRIGGERS = {"told", "tell", "tells"}

# "verb + to + store/school/hospital..." → missing article "the"
_PLACE_NEEDS_ARTICLE = {
    "store", "shop", "supermarket", "mall", "cinema", "movies",
    "theatre", "theater", "stadium", "gym", "pool", "library",
    "museum", "office", "hotel", "restaurant", "bar", "cafe",
    "station", "airport", "port", "terminal", "bank", "post",
}
# (school, hospital, church, prison, university, college = no article when used in their primary function)


def _add_ing(verb: str) -> str:
    """Add -ing to a verb with proper spelling: live→living, run→running."""
    if verb.endswith("ie"):
        return verb[:-2] + "ying"
    if verb.endswith("e") and not verb.endswith("ee"):
        return verb[:-1] + "ing"
    if (len(verb) >= 3 and verb[-1] in "bdgklmnprst"
            and verb[-2] in "aeiou" and verb[-3] not in "aeiou"):
        return verb + verb[-1] + "ing"
    return verb + "ing"


def _add_ed(verb: str) -> str:
    """Add -ed to a verb with proper spelling: live→lived, try→tried."""
    if verb.endswith("e"):
        return verb + "d"
    if verb.endswith("y") and len(verb) > 1 and verb[-2] not in "aeiou":
        return verb[:-1] + "ied"
    if (len(verb) >= 3 and verb[-1] in "bdgklmnprst"
            and verb[-2] in "aeiou" and verb[-3] not in "aeiou"):
        return verb + verb[-1] + "ed"
    return verb + "ed"


def _check_patterns(text: str) -> list[str]:
    """Check text for grammar patterns LanguageTool misses. Returns list of error descriptions."""
    words = text.lower().split()
    errors = []
    text_lower = text.lower()

    for i in range(len(words) - 1):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else ""
        nxt2 = words[i + 2] if i + 2 < len(words) else ""
        prev = words[i - 1] if i > 0 else ""
        prev2 = words[i - 2] if i > 1 else ""

        # ── Pattern 1: "been + base verb" (should be been + V-ing) ──
        # "had been wait", "has been work", "have been go"
        if w == "been" and nxt and _is_base_verb(nxt) and not nxt.endswith("ing"):
            if nxt not in {"to", "a", "an", "the", "my", "his", "her", "their", "its", "our", "your"}:
                if nxt in _BASE_FORMS or (not nxt.endswith(("tion", "sion", "ment", "ness"))):
                    errors.append(f"been {nxt} → been {_add_ing(nxt)}")

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
                    errors.append(f"{w} {nxt} → {w} {_add_ing(nxt)}")

        # ── Pattern 5: "have/has + base verb" (should be have + V3) ──
        # "I have go", "she has see", "we have take"
        if w in ("have", "has", "haven't", "hasn't", "havent", "hasnt") and nxt in _BASE_FORMS:
            if nxt in _IRREGULARS:
                past, pp = _IRREGULARS[nxt]
                if nxt != pp:  # base differs from past participle
                    errors.append(f"{w} {nxt} → {w} {pp}")
            elif nxt in _REGULAR_VERBS:
                errors.append(f"{w} {nxt} → {w} {_add_ed(nxt)}")

        # ── Pattern 6: "was/were + base verb" (should be V-ing or V3) ──
        # "I was go", "they were play"
        if w in ("was", "were") and nxt and _is_base_verb(nxt) and not nxt.endswith("ing"):
            if nxt not in {"not", "a", "an", "the", "my", "his", "her", "their", "its",
                          "our", "your", "this", "that", "no", "so", "too", "being",
                          "gonna", "going", "about", "supposed", "able", "just",
                          "never", "always", "also", "still", "even", "only",
                          "such", "what", "how", "why", "where", "when"}:
                if nxt in _BASE_FORMS:
                    errors.append(f"{w} {nxt} → {w} {_add_ing(nxt)}")

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
                if nxt in ("go", "do"):
                    errors.append(f"{w} {nxt} → {w} {nxt}es")
                elif nxt.endswith(("s", "sh", "ch", "x", "z")):
                    errors.append(f"{w} {nxt} → {w} {nxt}es")
                elif nxt.endswith("y") and len(nxt) > 1 and nxt[-2] not in "aeiou":
                    errors.append(f"{w} {nxt} → {w} {nxt[:-1]}ies")
                else:
                    errors.append(f"{w} {nxt} → {w} {nxt}s")

        # ── Pattern 10: "had + V2" (should be had + V3 for Past Perfect) ──
        # "had went" → "had gone", "had drank" → "had drunk"
        if w in ("had", "hadn't", "hadnt") and nxt in _PAST_TO_BASE:
            base = _PAST_TO_BASE[nxt]
            if base in _IRREGULARS:
                past, pp = _IRREGULARS[base]
                if nxt == past and past != pp:  # V2 used instead of V3
                    errors.append(f"had {nxt} → had {pp}")

        # ── Pattern 11: "if + would" (Conditional Type 2 error) ──
        # "if I would go" → "if I went"
        if w == "if" and nxt2 == "would":
            errors.append(f"if ... would → в if-clause нельзя would")
        if w == "if" and nxt == "would":
            errors.append(f"if would → в if-clause нельзя would")

        # ── Pattern 12: "would + V2" (should be would + base) ──
        # "I would went" → "I would go"
        if w in ("would", "wouldn't", "wouldnt") and nxt in _PAST_TO_BASE:
            base = _PAST_TO_BASE[nxt]
            if nxt != base:
                errors.append(f"would {nxt} → would {base}")

        # ── Pattern 13: "wish + can/have/am/is/are" (needs backshift) ──
        # "I wish I can" → "I wish I could"
        if w == "wish":
            if nxt == "i" and nxt2 in ("can", "have", "am", "will"):
                backshift = {"can": "could", "have": "had", "am": "were", "will": "would"}
                if nxt2 in backshift:
                    errors.append(f"wish I {nxt2} → wish I {backshift[nxt2]}")
            elif nxt2 in ("can", "is", "are", "will", "have", "has"):
                backshift = {"can": "could", "is": "were", "are": "were",
                            "will": "would", "have": "had", "has": "had"}
                if nxt2 in backshift:
                    errors.append(f"wish ... {nxt2} → wish ... {backshift[nxt2]}")

        # ── Pattern 14: double modals ──
        # "can could", "should must", "will can"
        if w in _DOUBLE_MODALS and nxt in _DOUBLE_MODALS:
            errors.append(f"{w} {nxt} → нельзя два модальных подряд")

        # ── Pattern 15: "since/for + present simple" (needs Perfect) ──
        # "I live here since 2010" → "I have lived here since 2010"
        if w in ("since", "for") and prev in _BASE_FORMS:
            # Check if subject before verb suggests present simple
            if prev2 in ("i", "we", "you", "they"):
                if prev in _IRREGULARS:
                    _, pp = _IRREGULARS[prev]
                    form = f"have {pp}"
                else:
                    form = f"have {_add_ed(prev)}"
                errors.append(f"{prev2} {prev} ... {w} → нужен Present Perfect ({form})")

        # ── Pattern 16: stative verbs in continuous ──
        # "I am knowing", "she is understanding", "we are believing"
        if w in ("am", "is", "are", "was", "were") and nxt and nxt.endswith("ing"):
            stem = nxt[:-3]  # remov-ing
            # Handle double consonant: "running" → "run"
            if stem and stem[-1] == stem[-2:]:
                stem = stem[:-1]
            if stem in _STATIVE_VERBS or nxt[:-3] in _STATIVE_VERBS:
                errors.append(f"{w} {nxt} → {stem} не используется в Continuous")

        # ── Pattern 17: "did ... used to" (should be "did ... use to") ──
        # "did used to", "did you used to", "didn't used to"
        if w == "used" and nxt == "to":
            # Check if "did" appears before (possibly with pronoun in between)
            if prev in ("did", "didn't", "didnt") or prev2 in ("did", "didn't", "didnt"):
                errors.append(f"did ... used to → did ... use to")

        # ── Pattern 18: passive V2 instead of V3 ──
        # "was send" → "was sent", "was broke" → "was broken"
        if w in ("was", "were", "been", "being", "be", "get", "got", "gets") and nxt in _PAST_TO_BASE:
            base = _PAST_TO_BASE[nxt]
            if base in _IRREGULARS:
                past, pp = _IRREGULARS[base]
                if nxt == past and past != pp:  # V2 used instead of V3 in passive
                    errors.append(f"{w} {nxt} → {w} {pp}")

        # ── Pattern 19: "looking forward to + base verb" ──
        # "looking forward to see" → "looking forward to seeing"
        if w == "forward" and nxt == "to" and prev == "looking":
            if nxt2 and _is_base_verb(nxt2) and not nxt2.endswith("ing"):
                if nxt2 in _BASE_FORMS:
                    errors.append(f"looking forward to {nxt2} → looking forward to {_add_ing(nxt2)}")

        # ── Pattern 20: "very/really + absolute adjective" ──
        # "very unique", "very perfect", "really complete"
        if w in ("very", "really", "extremely", "absolutely") and nxt in _ABSOLUTE_ADJECTIVES:
            errors.append(f"{w} {nxt} → {nxt} — абсолютное прилагательное, не нуждается в степени")

        # ── Pattern 21: negative adverb without inversion ──
        # "Never I have seen" → "Never have I seen"
        if w in ("never", "seldom", "rarely", "hardly", "scarcely", "barely", "nowhere", "neither"):
            if nxt in ("i", "he", "she", "it", "we", "they", "you"):
                if nxt2 in ("have", "has", "had", "was", "were", "am", "is", "are",
                           "do", "does", "did", "will", "would", "can", "could",
                           "should", "might", "may", "shall", "must"):
                    errors.append(
                        f"{w} {nxt} {nxt2} → {w} {nxt2} {nxt} (нужна инверсия после {w})"
                    )

        # ── Pattern 22: "should/could/might + V2" (should be + base) ──
        # "I should went", "she could saw", "they might broke"
        if w in ("should", "shouldn't", "shouldnt",
                 "could", "couldn't", "couldnt",
                 "might", "mightn't", "mightnt",
                 "may", "must", "shall", "can", "cannot", "can't", "cant"):
            if nxt in _PAST_TO_BASE:
                base = _PAST_TO_BASE[nxt]
                if nxt != base:
                    errors.append(f"{w} {nxt} → {w} {base}")

        # ── Pattern 25: causative "let + obj + to" (should be bare infinitive) ──
        # "let him to stay" → "let him stay"
        if w in ("let", "lets") and nxt in ("me", "him", "her", "us", "them", "it") and nxt2 == "to":
            errors.append(f"let {nxt} to ... → let {nxt} + bare infinitive (без to)")

        # ── Pattern 26: causative "made + obj + V-ing" (should be bare inf) ──
        # "made me crying" → "made me cry"
        if w == "made" and nxt in ("me", "him", "her", "us", "them", "it"):
            if nxt2 and nxt2.endswith("ing") and len(nxt2) > 3:
                # Reverse _add_ing: crying→cry, running→run, living→live
                stem = nxt2[:-3]
                if nxt2.endswith("ying") and len(nxt2) > 4:
                    candidate = nxt2[:-4] + "ie"  # dying→die, lying→lie
                    # Only use ie-form if it's a known verb (avoid crying→crie)
                    if candidate in _BASE_FORMS:
                        stem = candidate
                if stem and len(stem) >= 2 and stem[-1] == stem[-2]:
                    stem = stem[:-1]  # running→run, stopping→stop
                elif stem and not stem.endswith("e"):
                    # Check if adding back 'e' makes a known word: living→live
                    if (stem + "e") in _BASE_FORMS:
                        stem = stem + "e"
                errors.append(f"made {nxt} {nxt2} → made {nxt} {stem}")

        # ── Pattern 27: "it's time + present" (needs past) ──
        # "it's time we go" → "it's time we went"
        if w == "time" and prev in ("it's", "its", "is"):
            if nxt in ("we", "i", "you", "they", "he", "she"):
                if nxt2 in _BASE_FORMS:
                    if nxt2 in _IRREGULARS:
                        past_form = _IRREGULARS[nxt2][0]
                    else:
                        past_form = _add_ed(nxt2)
                    errors.append(f"it's time {nxt} {nxt2} → it's time {nxt} {past_form}")

        # ── Pattern 28: collective nouns + singular verb ──
        # "the police is coming" → "the police are coming"
        if w in _ALWAYS_PLURAL_NOUNS and nxt in ("is", "was", "has", "does"):
            plural_aux = {"is": "are", "was": "were", "has": "have", "does": "do"}
            errors.append(f"{w} {nxt} → {w} {plural_aux[nxt]} ({w} — всегда множественное)")

        # ── Pattern 29: "the" + country/city without article ──
        # "the France", "the Japan"
        if w == "the" and nxt in _NO_ARTICLE_PLACES:
            errors.append(f"the {nxt} → {nxt} (без артикля)")

        # ── Pattern 30: Only/Not only/Hardly + subject without inversion ──
        # "Only then I realized" → "Only then did I realize"
        if w in ("only", "hardly", "scarcely", "no sooner"):
            if prev2 == "" or prev == "":  # at/near sentence start
                if nxt2 and nxt2 in ("i", "he", "she", "it", "we", "they", "you"):
                    # nxt is the adverb/time word, nxt2 is subject — no inversion
                    nxt3 = words[i + 3] if i + 3 < len(words) else ""
                    if nxt3 and (nxt3 in _BASE_FORMS or nxt3 in _PAST_FORMS
                               or nxt3.endswith("ed") or nxt3.endswith("ing")
                               or nxt3 in {"have", "has", "had", "was", "were",
                                           "am", "is", "are"}):
                        errors.append(
                            f"{w} {nxt} {nxt2} {nxt3} → нужна инверсия после {w}"
                        )

        # ── Pattern 35: "been + V3/V-ed" (should be been + V-ing for continuous) ──
        # "have been waited" → "have been waiting", "has been gone" → "has been going"
        if w == "been" and nxt:
            # V-ed form (regular): "been waited", "been played"
            if nxt.endswith("ed") and len(nxt) > 3 and nxt not in {"used", "supposed"}:
                if nxt in _ALL_V3 or nxt in _REGULAR_ED:
                    errors.append(f"been {nxt} → been + V-ing? (возможно Perfect Continuous)")
            # V3 irregular: "been gone", "been taken" (when V-ing is expected)
            if nxt in _V3_FORMS and nxt not in _BASE_FORMS:
                base = _PAST_TO_BASE.get(nxt, nxt)
                if base != nxt:  # V3 differs from base → likely wrong
                    errors.append(f"been {nxt} → been {_add_ing(base)}? (Perfect Continuous)")

        # ── Pattern 36: "used to + V-ing" (should be "used to + base") ──
        # BUT: "am/is/are used to + V-ing" is CORRECT (be used to = привык)
        # "I am used to wake up" → "I am used to waking up"
        if w == "used" and nxt == "to" and prev in ("am", "is", "are", "was", "were",
                                                     "get", "got", "getting", "been"):
            if nxt2 and _is_base_verb(nxt2) and not nxt2.endswith("ing"):
                if nxt2 in _BASE_FORMS:
                    errors.append(
                        f"be used to {nxt2} → be used to {_add_ing(nxt2)} "
                        f"(после be used to — герундий)"
                    )

        # ── Pattern 37: "would rather + subj + base" (needs past for diff subject) ──
        # "I would rather you go" → "I would rather you went"
        if w == "rather" and prev in ("would", "wouldn't", "wouldnt", "'d"):
            if nxt in ("you", "he", "she", "we", "they", "it"):
                if nxt2 in _BASE_FORMS and nxt2 != "had":
                    errors.append(
                        f"would rather {nxt} {nxt2} → would rather {nxt} + Past Simple "
                        f"(для другого субъекта нужно прошедшее)"
                    )

        # ── Pattern 38: "needs/need + V3/V-ed" without "to be" ──
        # "The car needs repaired" → "needs repairing" or "needs to be repaired"
        if w in ("need", "needs") and nxt:
            if nxt.endswith("ed") and len(nxt) > 4 and nxt not in {"indeed", "need", "speed"}:
                # Any -ed word after needs is suspect (don't require it in our verb list)
                errors.append(f"{w} {nxt} → {w} V-ing или {w} to be {nxt}")
            # Also irregular V3: "needs broken", "needs written"
            elif nxt in _V3_FORMS and nxt not in _BASE_FORMS:
                base = _PAST_TO_BASE.get(nxt, "")
                if base:
                    errors.append(
                        f"{w} {nxt} → {w} {_add_ing(base)} или {w} to be {nxt}"
                    )

        # ── Pattern 39: "so much + adj" (should be "so" without "much") ──
        # "so much expensive" → "so expensive"
        # "so much" before adj is wrong; before noun is fine ("so much money")
        if w == "so" and nxt == "much":
            if nxt2 and nxt2.endswith(("ive", "ous", "ful", "ant", "ent", "ble", "al",
                                       "ish", "ary", "ic")):
                errors.append(f"so much {nxt2} → so {nxt2} (so much — только перед существительными)")
            # Common adjectives that don't end in those suffixes
            if nxt2 in {"big", "small", "good", "bad", "old", "new", "long", "short",
                        "high", "low", "fast", "slow", "hard", "soft", "hot", "cold",
                        "cheap", "rich", "poor", "young", "tall", "dark", "bright",
                        "loud", "quiet", "warm", "cool", "clean", "dirty", "dry", "wet",
                        "deep", "wide", "thin", "thick", "heavy", "light", "sweet",
                        "strong", "weak", "nice", "fine", "safe", "rare", "rude", "late",
                        "strict", "proud", "glad", "smart"}:
                errors.append(f"so much {nxt2} → so {nxt2} (so much — только перед существительными)")

        # ── Pattern 40: "despite + clause" (needs "despite the fact that" or "although") ──
        # "despite he was tired" → "despite being tired" / "although he was tired"
        if w == "despite" and nxt in ("i", "he", "she", "it", "we", "they", "you"):
            errors.append(
                f"despite {nxt}... → despite — предлог, не союз. "
                f"Нужно: although {nxt}... / despite the fact that {nxt}..."
            )

        # ── Pattern 41: "suggest + obj + to" (should be suggest + V-ing / suggest that) ──
        # "I suggest him to go" → "I suggest that he go" / "I suggest going"
        if w in ("suggest", "suggested", "suggests") and nxt2 == "to":
            if nxt in ("me", "him", "her", "us", "them", "it"):
                errors.append(
                    f"{w} {nxt} to → suggest не используется с obj + to. "
                    f"Нужно: {w} that ... / {w} {_add_ing(words[i+3]) if i+3 < len(words) and words[i+3] in _BASE_FORMS else 'V-ing'}"
                )

        # ── Pattern 42: "even + subj + verb" without "though/if" ──
        # "even I tried" → "even though I tried"
        if w == "even" and nxt in ("i", "he", "she", "it", "we", "they", "you"):
            if nxt not in ("if", "though", "when", "so"):
                # Check that next word after subject is a verb
                if nxt2 and (nxt2 in _BASE_FORMS or nxt2 in _PAST_FORMS or nxt2.endswith("ed")):
                    # But "even I know" is valid (emphatic). Only flag if it looks like a clause start
                    # Check if there's a main clause after (another subject+verb)
                    rest = " ".join(words[i+3:])
                    has_main_clause = bool(re.search(r'\b(i|he|she|it|we|they|you)\s+\w+', rest))
                    if has_main_clause:
                        errors.append(
                            f"even {nxt} {nxt2} → even though/even if {nxt} {nxt2}? "
                            f"(even без though/if не является союзом)"
                        )

        # ── Pattern 43: "neither ... nor ... was" (agreement with nearest noun) ──
        # Complex — just catch "nor the/a PLURAL_NOUN was"
        if w == "nor":
            # Look ahead for "was" after plural subject
            for j in range(i + 1, min(i + 5, len(words))):
                if words[j] == "was" and j > i + 1:
                    # Check if noun before "was" is likely plural
                    noun_before = words[j - 1]
                    if noun_before.endswith("s") and not noun_before.endswith(("ss", "us", "is")):
                        errors.append(
                            f"nor ... {noun_before} was → nor ... {noun_before} were "
                            f"(согласование с ближайшим существительным)"
                        )
                    break

        # ── Pattern 45: "make + DO-noun" (should be DO) ──
        # "make homework", "make exercise", "make shopping"
        if w in ("make", "makes", "made", "making") and nxt in _DO_NOT_MAKE:
            errors.append(f"make {nxt} → do {nxt}")

        # ── Pattern 46: "do + MAKE-noun" (should be MAKE) ──
        # "do a mistake", "do a decision", "do a phone call"
        if w in ("do", "does", "did", "doing") and nxt2:
            phrase2 = f"{nxt} {nxt2}"
            if phrase2 in _MAKE_NOT_DO:
                errors.append(f"do {phrase2} → make {phrase2}")
            elif nxt in _MAKE_NOT_DO:
                errors.append(f"do {nxt} → make {nxt}")

        # ── Pattern 47: "in + day of week" (should be "on") ──
        # "in Monday", "in Friday"
        if w == "in" and nxt in _DAYS_OF_WEEK:
            errors.append(f"in {nxt} → on {nxt}")

        # ── Pattern 48: "in + number + month" (should be "on") ──
        # "in 15 March", "born in 5 July"
        if w == "in" and nxt and nxt.isdigit() and nxt2 in _MONTHS:
            errors.append(f"in {nxt} {nxt2} → on {nxt} {nxt2}")

        # ── Pattern 49: "I am agree/disagree" (agree is a verb, not adjective) ──
        if w in ("am", "is", "are", "was", "were") and nxt in _AM_ADJECTIVE_ERRORS:
            fix = _AM_ADJECTIVE_ERRORS[nxt]
            if fix:
                errors.append(f"{w} {nxt} → {fix}")

        # ── Pattern 50: "told/tell + that" without object ──
        # "she told that she was tired" → "she told me/him that..."
        if w in _TELL_TRIGGERS and nxt == "that":
            errors.append(
                f"{w} that → {w} + объект + that "
                f"(tell всегда требует объекта: told me/him/her/us that...)"
            )

        # ── Pattern 51: redundant pairs ──
        # Checked below as multi-word — but catch "very much + adj" in loop
        if w == "very" and nxt == "much" and nxt2 and len(nxt2) > 2:
            # "very much + adjective" is wrong
            if nxt2.endswith(("y", "ed", "ry", "sy", "py", "sy")) or nxt2 in {
                "hungry", "tired", "busy", "happy", "angry", "sad", "glad",
                "sick", "cold", "hot", "big", "small", "tall", "short",
            }:
                errors.append(f"very much {nxt2} → very {nxt2}")

        # ── Pattern 52: "how long time" → "how long" ──
        if w == "long" and nxt == "time" and prev == "how":
            errors.append(f"how long time → how long (time — лишнее слово)")

        # ── Pattern 53: "My mother she / My friend he" (redundant subject pronoun) ──
        if w in ("she", "he", "they", "it", "we") and prev in ("mother", "father",
            "sister", "brother", "friend", "teacher", "boss", "wife", "husband",
            "son", "daughter", "dog", "cat", "car", "house", "team", "company"):
            errors.append(
                f"{prev} {w} → {prev} ... (местоимение-подлежащее лишнее после существительного)"
            )

        # ── Pattern 54: "went/go to store/shop" without article ──
        # "I went to store" → "I went to the store"
        if w == "to" and nxt in _PLACE_NEEDS_ARTICLE:
            # Only flag if no article before
            if prev not in ("the", "a", "an", "this", "that", "my", "your",
                            "his", "her", "our", "their", "its", "some", "any"):
                errors.append(f"to {nxt} → to the {nxt} (нужен артикль)")

        # ── Pattern 55: "although X but Y" — но лишнее ──
        # Handled below via regex

        # ── Pattern 56: "he is best / she is oldest" — missing article ──
        # "he is best student" → "he is the best student"
        if w in ("am", "is", "are", "was", "were") and nxt in ("best", "worst",
                 "only", "first", "last", "same", "next"):
            if nxt2 and nxt2 not in ("the", "a", "an", "one", "thing"):
                # Check that prev isn't "the"
                if prev not in ("the",):
                    errors.append(
                        f"{w} {nxt} {nxt2} → {w} the {nxt} {nxt2} (супerlative/only требует 'the')"
                    )

    # ── Pattern 23: wrong verb-preposition collocations (multi-word) ──
    for wrong, correct in _WRONG_PREPOSITIONS.items():
        if wrong in text_lower:
            errors.append(f"{wrong} → {correct}")

    # ── Pattern 44: "it's time" + present tense (regex for broader coverage) ──
    its_time = re.search(
        r"\b(?:it'?s|it\s+is)\s+(?:high\s+)?time\s+(i|we|you|they|he|she)\s+("
        + "|".join(_BASE_FORMS) + r")\b",
        text_lower
    )
    if its_time:
        subj = its_time.group(1)
        verb = its_time.group(2)
        errors.append(f"it's time {subj} {verb} → it's time + Past Simple")

    # ── Pattern 31: uncountable nouns with plural -s ──
    # Skip nouns whose plural form is also a common verb (works, travels, etc.)
    _UNCOUNTABLE_ALSO_VERB = {"work", "travel", "water", "milk", "salt", "sugar",
                              "butter", "rice", "rain", "progress", "research",
                              "weather", "traffic", "staff", "fruit", "hair"}
    for noun in _UNCOUNTABLE_NOUNS:
        if noun in _UNCOUNTABLE_ALSO_VERB:
            continue  # skip — "works" / "travels" are too ambiguous with verb forms
        plural = noun + "s"
        if plural in words:
            errors.append(f"{plural} → {noun} (неисчисляемое, нельзя во множественном)")

    # ── Pattern 32: Russisms / false friends ──
    for pattern, fix in _RUSSISMS.items():
        if fix is not None and pattern in text_lower:
            errors.append(f"{pattern} → {fix}")

    # ── Pattern 33: indirect question with inversion ──
    # "I asked where did he go" → "I asked where he went"
    indirect_q = re.search(
        r'\b(' + '|'.join(_INDIRECT_Q_TRIGGERS) + r')\b.*\b(where|when|why|how|what|who|whether|if)'
        r'\s+(did|does|do|has|have|had|is|are|was|were|will|would|can|could)\s+'
        r'(i|he|she|it|we|they|you)\b',
        text_lower
    )
    if indirect_q:
        aux = indirect_q.group(3)
        subj = indirect_q.group(4)
        errors.append(
            f"...{indirect_q.group(2)} {aux} {subj}... → "
            f"в косвенном вопросе прямой порядок слов: {indirect_q.group(2)} {subj} ..."
        )

    # ── Pattern 34: "arrive + noun" without preposition ──
    # "arrive the station" → "arrive at the station"
    arrive_match = re.search(
        r'\b(arrive|arrived|arrives)\s+(the|a|an|this|that|my|his|her|our|their)\b',
        text_lower
    )
    if arrive_match:
        errors.append(
            f"{arrive_match.group(1)} {arrive_match.group(2)}... → "
            f"{arrive_match.group(1)} at/in {arrive_match.group(2)}..."
        )

    # ── Pattern 55: "although/even though X but Y" — but redundant ──
    if _ALTHOUGH_BUT.search(text_lower):
        errors.append(
            "although ... but → нельзя использовать both: "
            "либо although/even though, либо but — не оба вместе"
        )

    # ── Pattern 57: redundant word pairs ──
    for wrong, correct in _REDUNDANT_PAIRS.items():
        if wrong in text_lower:
            errors.append(f"{wrong} → {correct} (тавтология)")

    # ── Pattern 58: "make + DO-nouns" multi-word ──
    # "make my homework", "make some exercise"
    make_do = re.search(
        r'\b(make|makes|made|making)\s+(?:my|his|her|our|your|their|some|the|a|an)?\s*('
        + '|'.join(_DO_NOT_MAKE) + r')\b',
        text_lower
    )
    if make_do:
        noun = make_do.group(2)
        errors.append(f"make ... {noun} → do ... {noun}")

    # ── Pattern 59: "do a photo / do photos" → "take a photo" ──
    do_photo = re.search(
        r'\b(do|does|did|doing)\s+(?:a|some|the)?\s*(photo|photos|picture|pictures|screenshot|screenshots)\b',
        text_lower
    )
    if do_photo:
        errors.append(f"do {do_photo.group(2)} → take {do_photo.group(2)}")

    # ── Pattern 24: "since/for" at end after present simple ──
    # "I work here since 2010" — regex-based
    since_for_match = re.search(
        r'\b(i|we|you|they)\s+(live|work|stay|study|know|play|wait|teach)\b.*\b(since|for)\b',
        text_lower
    )
    if since_for_match:
        subj = since_for_match.group(1)
        verb = since_for_match.group(2)
        prep = since_for_match.group(3)
        if verb in _IRREGULARS:
            _, pp = _IRREGULARS[verb]
            form = f"have {pp}"
        else:
            form = f"have {_add_ed(verb)}"
        errors.append(f"{subj} {verb} ... {prep} → нужен Present Perfect ({form} ... {prep})")

    # "he/she lives ... since" pattern
    since_for_3rd = re.search(
        r'\b(he|she|it)\s+(lives|works|stays|studies|knows|plays|waits|teaches)\b.*\b(since|for)\b',
        text_lower
    )
    if since_for_3rd:
        subj = since_for_3rd.group(1)
        verb = since_for_3rd.group(2)
        prep = since_for_3rd.group(3)
        # Strip the -s/-es to get base form
        base = verb[:-1] if verb.endswith("s") else verb
        if base in _IRREGULARS:
            _, pp = _IRREGULARS[base]
        else:
            pp = _add_ed(base)
        errors.append(f"{subj} {verb} ... {prep} → нужен Present Perfect (has {pp} ... {prep})")

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
        if any(rule_id.startswith(p) for p in SKIP_RULE_PREFIXES):
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

async def has_errors(text: str, use_gpt_fallback: bool = True) -> bool:
    """
    3-layer grammar error detector:
    1. Pattern checker  — instant, free, catches ~40 specific ESL patterns
    2. LanguageTool API — fast, free, catches 5000+ rule-based errors
    3. GPT mini-check   — cheap ($0.000015), catches ANYTHING incl. word order

    Returns True if errors found, False if clean.
    """
    # ── Layer 1: Pattern checker (instant, free) ──
    pattern_errors = _check_patterns(text)
    if pattern_errors:
        logger.info(f"[L1-Pattern] found: {pattern_errors[:2]}")
        return True

    # ── Layer 2: LanguageTool API (fast, free) ──
    lt_errors = await check_local(text)
    if lt_errors is None:
        logger.warning("[L2-LT] API failed → fallback to GPT mini-check")
        # Don't return True immediately — try GPT mini-check
    elif lt_errors:
        logger.info(f"[L2-LT] found: {[(e['rule'], e['original']) for e in lt_errors]}")
        return True

    # ── Layer 3: GPT mini-check (cheap, catches word order / naturalness) ──
    if not use_gpt_fallback:
        return False

    # Only run for messages with 5+ words — short phrases rarely have catchable errors
    # and mini-check has more false positives on short text
    words = text.split()
    if len(words) < 5:
        return False

    from bot.services.groq_client import ask_grammar_check
    result = await ask_grammar_check(text)
    if result is True:
        logger.info(f"[L3-GPT] mini-check flagged: '{text[:60]}'")
        return True
    if result is None:
        logger.warning("[L3-GPT] mini-check failed → assume no error")

    return False
