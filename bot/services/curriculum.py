from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import GrammarUsage

# Constructions required per level (ordered by priority)
CURRICULUM: dict[str, list[str]] = {
    "A2": [
        "present_simple",
        "present_continuous",
        "past_simple",
        "future_will",
        "future_going_to",
        "modal_can",
        "modal_should",
        "comparative",
        "superlative",
        "there_is_there_are",
    ],
    "B1": [
        "present_perfect",
        "past_continuous",
        "past_perfect",
        "first_conditional",
        "second_conditional",
        "passive_voice",
        "modal_must",
        "modal_might",
        "relative_clause",
        "gerund_infinitive",
    ],
    "B2": [
        "present_perfect_continuous",
        "past_perfect_continuous",
        "third_conditional",
        "mixed_conditional",
        "reported_speech",
        "passive_voice_advanced",
        "inversion",
        "cleft_sentence",
        "subjunctive",
        "modal_perfect",
    ],
}

CONSTRUCTION_NAMES: dict[str, str] = {
    "present_simple": "Present Simple",
    "present_continuous": "Present Continuous",
    "past_simple": "Past Simple",
    "future_will": "Future (will)",
    "future_going_to": "Future (going to)",
    "modal_can": "Modal: can/can't",
    "modal_should": "Modal: should/shouldn't",
    "comparative": "Сравнительная степень",
    "superlative": "Превосходная степень",
    "there_is_there_are": "There is / There are",
    "present_perfect": "Present Perfect",
    "past_continuous": "Past Continuous",
    "past_perfect": "Past Perfect",
    "first_conditional": "1st Conditional",
    "second_conditional": "2nd Conditional",
    "passive_voice": "Passive Voice",
    "modal_must": "Modal: must/have to",
    "modal_might": "Modal: might/could",
    "relative_clause": "Relative Clauses",
    "gerund_infinitive": "Gerund vs Infinitive",
    "present_perfect_continuous": "Present Perfect Continuous",
    "past_perfect_continuous": "Past Perfect Continuous",
    "third_conditional": "3rd Conditional",
    "mixed_conditional": "Mixed Conditional",
    "reported_speech": "Reported Speech",
    "passive_voice_advanced": "Passive Voice (advanced)",
    "inversion": "Inversion",
    "cleft_sentence": "Cleft Sentences",
    "subjunctive": "Subjunctive Mood",
    "modal_perfect": "Modal Perfect (should have)",
}

# Map GrammarUsage.construction values → curriculum keys
_GRAMMAR_USAGE_MAP: dict[str, str] = {
    "present_simple": "present_simple",
    "present_continuous": "present_continuous",
    "past_simple": "past_simple",
    "past_continuous": "past_continuous",
    "past_perfect": "past_perfect",
    "present_perfect": "present_perfect",
    "present_perfect_continuous": "present_perfect_continuous",
    "past_perfect_continuous": "past_perfect_continuous",
    "future_will": "future_will",
    "future_going_to": "future_going_to",
    "conditional_1": "first_conditional",
    "conditional_2": "second_conditional",
    "conditional_3": "third_conditional",
    "conditional_mixed": "mixed_conditional",
    "passive_voice": "passive_voice",
    "reported_speech": "reported_speech",
    "modal_can": "modal_can",
    "modal_should": "modal_should",
    "modal_must": "modal_must",
    "modal_might": "modal_might",
    "modal_perfect": "modal_perfect",
    "relative_clause": "relative_clause",
    "gerund": "gerund_infinitive",
    "infinitive": "gerund_infinitive",
}

MASTERED_THRESHOLD = 3  # times used correctly to consider mastered

LEVEL_DESCRIPTIONS = {
    "A2": "Базовые времена и структуры",
    "B1": "Сложные времена, условные, пассив",
    "B2": "Продвинутые конструкции",
}


async def get_curriculum_progress(session: AsyncSession, user_id: int) -> dict:
    """Returns progress per level: which constructions used, which missing."""
    result = await session.execute(
        select(GrammarUsage.construction, GrammarUsage.times_used)
        .where(GrammarUsage.user_id == user_id)
    )
    usages = {row.construction: row.times_used for row in result.all()}

    # Map to curriculum keys — also count partial progress (used but < threshold)
    mastered_keys: set[str] = set()
    in_progress: dict[str, int] = {}  # key → times used

    for usage_key, times in usages.items():
        curriculum_key = _GRAMMAR_USAGE_MAP.get(usage_key)
        if not curriculum_key:
            continue
        if times >= MASTERED_THRESHOLD:
            mastered_keys.add(curriculum_key)
        else:
            in_progress[curriculum_key] = max(in_progress.get(curriculum_key, 0), times)

    progress = {}
    for level, constructions in CURRICULUM.items():
        done = [c for c in constructions if c in mastered_keys]
        partial = {c: in_progress[c] for c in constructions if c in in_progress}
        todo = [c for c in constructions if c not in mastered_keys]
        progress[level] = {
            "done": done,
            "partial": partial,
            "todo": todo,
            "total": len(constructions),
        }

    return progress


def format_level_text(progress: dict, level: str) -> str:
    data = progress.get(level, {})
    done = data.get("done", [])
    partial = data.get("partial", {})
    todo = data.get("todo", [])
    total = data.get("total", 1)

    filled = len(done) * 10 // total
    bar = "█" * filled + "░" * (10 - filled)
    pct = round(len(done) / total * 100)

    lines = [
        f"📈 {level} — {LEVEL_DESCRIPTIONS.get(level, '')}",
        f"[{bar}] {len(done)}/{total} освоено ({pct}%)",
        "",
    ]

    if done:
        lines.append("✅ Освоено:")
        for c in done:
            lines.append(f"  • {CONSTRUCTION_NAMES.get(c, c)}")
        lines.append("")

    if partial:
        lines.append("🔄 В процессе:")
        for c, times in partial.items():
            lines.append(f"  • {CONSTRUCTION_NAMES.get(c, c)} ({times}/{MASTERED_THRESHOLD}×)")
        lines.append("")

    next_targets = [c for c in todo if c not in partial][:3]
    if next_targets:
        lines.append("🎯 Следующие цели:")
        for c in next_targets:
            lines.append(f"  • {CONSTRUCTION_NAMES.get(c, c)}")
        lines.append("")

    lines.append("💡 Конструкция засчитывается когда бот видит её в твоих сообщениях 3+ раз.")
    return "\n".join(lines)


def get_next_curriculum_construction(progress: dict, english_level: str | None) -> str | None:
    """Return the next construction to focus on in daily challenge."""
    order = ["A2", "B1", "B2"]
    if english_level in order:
        start = order.index(english_level)
        order = order[start:] + order[:start]

    for level in order:
        todo = progress.get(level, {}).get("todo", [])
        if todo:
            return todo[0]
    return None
