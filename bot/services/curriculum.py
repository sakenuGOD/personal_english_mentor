from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import GrammarUsage, Error, User

# Human-readable info for each topic shown in "Мой путь"
TOPIC_INFO: dict[str, dict] = {
    "present_perfect": {
        "name": "Present Perfect",
        "emoji": "⏱",
        "hint": "Когда действие в прошлом, но важно сейчас",
        "example": '"I have seen" vs "I saw"',
    },
    "past_perfect": {
        "name": "Past Perfect",
        "emoji": "⏮",
        "hint": "Действие случилось ДО другого действия в прошлом",
        "example": '"I had eaten before she arrived"',
    },
    "present_perfect_continuous": {
        "name": "Present Perfect Continuous",
        "emoji": "🔄",
        "hint": "Действие началось в прошлом и всё ещё идёт",
        "example": '"I have been working here for 3 years"',
    },
    "past_continuous": {
        "name": "Past Continuous",
        "emoji": "📽",
        "hint": "Действие было в процессе в прошлом",
        "example": '"I was sleeping when he called"',
    },
    "passive_voice": {
        "name": "Пассивный залог",
        "emoji": "🔀",
        "hint": "Когда важно что произошло, а не кто сделал",
        "example": '"The report was written by the team"',
    },
    "conditionals": {
        "name": "Условные предложения",
        "emoji": "🔀",
        "hint": "If + правило: 3 типа для разных ситуаций",
        "example": '"If I had known, I would have called"',
    },
    "articles": {
        "name": "Артикли a/an/the",
        "emoji": "📌",
        "hint": "a = первый раз / the = уже знаем о чём / ∅ = обобщение",
        "example": '"I saw a dog. The dog was huge."',
    },
    "prepositions": {
        "name": "Предлоги",
        "emoji": "📍",
        "hint": "in/on/at/to/for/of — у каждого своя логика",
        "example": '"depend on", "good at", "interested in"',
    },
    "word_order": {
        "name": "Порядок слов",
        "emoji": "🔤",
        "hint": "Subject + Verb + Object — в английском строгий порядок",
        "example": '"I always drink coffee" (не "always I drink")',
    },
    "subject_verb_agreement": {
        "name": "Согласование подлежащего",
        "emoji": "🔗",
        "hint": "He/She/It → глагол + s. They/I/We → без s",
        "example": '"She goes" vs "They go"',
    },
    "modal_verbs": {
        "name": "Модальные глаголы",
        "emoji": "🎛",
        "hint": "can/could/should/must/might — каждый своя степень",
        "example": '"You should" (совет) vs "You must" (обязанность)"',
    },
    "tenses_general": {
        "name": "Выбор времени",
        "emoji": "🕐",
        "hint": "Past Simple vs Present Perfect: с датой → Simple, без → Perfect",
        "example": '"I saw him yesterday" vs "I have seen him"',
    },
    "gerund_infinitive": {
        "name": "Герундий vs Инфинитив",
        "emoji": "⚖️",
        "hint": "enjoy/avoid/finish + ing. want/hope/decide + to",
        "example": '"I enjoy swimming" vs "I want to swim"',
    },
    "reported_speech": {
        "name": "Косвенная речь",
        "emoji": "💬",
        "hint": "При пересказе времена сдвигаются назад",
        "example": '"He said he was tired" (не "is")',
    },
    "naturalness": {
        "name": "Натуральность речи",
        "emoji": "🗣",
        "hint": "Грамматика правильная, но так не говорят",
        "example": '"I desire to consume food" → "I want to eat"',
    },
}

# Map Error.category / rule_name patterns → topic keys
_ERROR_TOPIC_MAP: list[tuple[str, str]] = [
    ("present_perfect", "present_perfect"),
    ("past_perfect", "past_perfect"),
    ("present_perfect_continuous", "present_perfect_continuous"),
    ("past_continuous", "past_continuous"),
    ("PASSIVE", "passive_voice"),
    ("passive", "passive_voice"),
    ("CONDITIONAL", "conditionals"),
    ("conditional", "conditionals"),
    ("ARTICLES", "articles"),
    ("article", "articles"),
    ("EN_A_VS_AN", "articles"),
    ("PREPOSITION", "prepositions"),
    ("preposition", "prepositions"),
    ("WRONG_PREPOSITION", "prepositions"),
    ("WORD_ORDER", "word_order"),
    ("subject_verb", "subject_verb_agreement"),
    ("HE_VERB", "subject_verb_agreement"),
    ("MODAL", "modal_verbs"),
    ("modal", "modal_verbs"),
    ("TENSE", "tenses_general"),
    ("tense", "tenses_general"),
    ("GERUND", "gerund_infinitive"),
    ("gerund", "gerund_infinitive"),
    ("REPORTED", "reported_speech"),
    ("STYLE", "naturalness"),
    ("naturalness", "naturalness"),
]

LEVEL_NEXT = {"A1": "A2", "A2": "B1", "B1": "B2", "B2": "C1", "C1": "C2"}
LEVEL_LABEL = {"A1": "Начинающий", "A2": "Элементарный", "B1": "Средний", "B2": "Выше среднего", "C1": "Продвинутый", "C2": "Мастер"}


def _map_error_to_topic(category: str, rule_name: str) -> str | None:
    text = f"{category or ''} {rule_name or ''}".lower()
    for pattern, topic in _ERROR_TOPIC_MAP:
        if pattern.lower() in text:
            return topic
    return None


async def get_path_data(session: AsyncSession, user_id: int) -> dict:
    """Returns weak topics based on real errors + user level."""
    # Get user level
    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    english_level = user.english_level if user else None

    # Aggregate errors by topic
    errors_result = await session.execute(
        select(Error.category, Error.rule_name, func.count(Error.id).label("cnt"))
        .where(Error.user_id == user_id)
        .group_by(Error.category, Error.rule_name)
        .order_by(func.count(Error.id).desc())
    )
    rows = errors_result.all()

    topic_counts: dict[str, int] = {}
    for category, rule_name, cnt in rows:
        topic = _map_error_to_topic(category or "", rule_name or "")
        if topic:
            topic_counts[topic] = topic_counts.get(topic, 0) + cnt

    # Sort by error count
    sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)

    # Total error count
    total_errors = (await session.execute(
        select(func.count(Error.id)).where(Error.user_id == user_id)
    )).scalar() or 0

    return {
        "level": english_level,
        "weak_topics": sorted_topics[:5],  # top 5 weak areas
        "total_errors": total_errors,
        "has_data": total_errors > 0,
    }


def format_path_text(data: dict) -> str:
    level = data.get("level")
    weak_topics = data.get("weak_topics", [])
    total_errors = data.get("total_errors", 0)
    has_data = data.get("has_data", False)

    lines = ["📈 Мой путь\n"]

    # Level block
    if level:
        label = LEVEL_LABEL.get(level, level)
        next_level = LEVEL_NEXT.get(level)
        lines.append(f"🎓 Твой уровень: {level} — {label}")
        if next_level:
            lines.append(f"🎯 Цель: {next_level} — {LEVEL_LABEL.get(next_level, next_level)}")
    else:
        lines.append("❓ Уровень не определён")
        lines.append("Пройди тест: Прогресс → Тренировки → 📋 Тест на уровень")

    lines.append("")

    if not has_data:
        lines.append("📊 Пока нет данных об ошибках.")
        lines.append("Общайся в бизнес-чатах — бот соберёт статистику и покажет над чем работать.")
        return "\n".join(lines)

    # Weak spots
    lines.append(f"📉 Слабые места (из {total_errors} ошибок):\n")
    for i, (topic, count) in enumerate(weak_topics, 1):
        info = TOPIC_INFO.get(topic, {"name": topic, "emoji": "•", "hint": "", "example": ""})
        lines.append(f"{i}. {info['emoji']} {info['name']} — {count} ошиб.")
        if info.get("hint"):
            lines.append(f"   {info['hint']}")
        if info.get("example"):
            lines.append(f"   Пример: {info['example']}")
        lines.append("")

    lines.append("💡 Нажми на тему чтобы потренироваться →")
    return "\n".join(lines)
