from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💬 AI Чат"), KeyboardButton(text="📝 Проверить текст")],
            [KeyboardButton(text="🔄 Как сказать"), KeyboardButton(text="💡 Слово")],
            [KeyboardButton(text="🤔 Что имел ввиду"), KeyboardButton(text="📊 Прогресс")],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def check_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Проверить ещё", callback_data="check:another")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
    ])


def howtosay_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Ещё фразу", callback_data="how:another"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="menu"),
        ],
    ])


def word_result_keyboard(word: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ В словарь", callback_data=f"word:add:{word}"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="menu"),
        ],
    ])


def meaning_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Ещё фразу", callback_data="meaning:another"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="menu"),
        ],
    ])


def ai_chat_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
    ])


def progress_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎯 Провериться", callback_data="progress:workout_menu"),
            InlineKeyboardButton(text="🔍 Анализ", callback_data="progress:analysis"),
        ],
        [
            InlineKeyboardButton(text="📚 Словарь", callback_data="progress:vocab"),
            InlineKeyboardButton(text="📓 Ошибки", callback_data="progress:mistakes"),
        ],
        [
            InlineKeyboardButton(text="🗺 Грамматика", callback_data="progress:grammar_map"),
            InlineKeyboardButton(text="📊 Неделя", callback_data="progress:weekly"),
        ],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
    ])


def workout_menu_keyboard(challenge_done: bool = False) -> InlineKeyboardMarkup:
    challenge_text = "✅ Задание дня выполнено" if challenge_done else "🌅 Задание дня (+30 XP)"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=challenge_text, callback_data="workout:daily_challenge")],
        [InlineKeyboardButton(text="📝 Тест по ошибкам", callback_data="workout:test")],
        [InlineKeyboardButton(text="🎯 Общая тренировка", callback_data="workout:general")],
        [InlineKeyboardButton(text="🇷🇺→🇬🇧 Переведи фразу", callback_data="workout:translation")],
        [InlineKeyboardButton(text="📋 Тест на уровень", callback_data="workout:level_test")],
        [InlineKeyboardButton(text="🎭 Диалог-тренировка", callback_data="workout:roleplay")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="progress:back")],
    ])


def workout_count_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="5", callback_data="workout:config:count:5"),
            InlineKeyboardButton(text="10", callback_data="workout:config:count:10"),
            InlineKeyboardButton(text="15", callback_data="workout:config:count:15"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="progress:workout_menu")],
    ])


def workout_hints_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💡 С подсказками", callback_data="workout:config:hints:yes"),
            InlineKeyboardButton(text="🧠 Без подсказок", callback_data="workout:config:hints:no"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="progress:workout_menu")],
    ])


def workout_skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="workout:skip")],
    ])


def workout_done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Ещё раз", callback_data="workout:test"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="menu"),
        ],
    ])


def roleplay_scenarios_keyboard() -> InlineKeyboardMarkup:
    scenarios = [
        ("💼 Job Interview", "role:start:job_interview"),
        ("🍽 Restaurant", "role:start:restaurant"),
        ("🏨 Hotel Check-in", "role:start:hotel_checkin"),
        ("📞 Tech Support", "role:start:tech_support"),
        ("🤝 Smalltalk", "role:start:smalltalk"),
        ("🛒 Return Item", "role:start:return_item"),
        ("✈️ Airport", "role:start:airport"),
        ("🏥 Doctor Visit", "role:start:doctor_visit"),
        ("💰 Salary Talk", "role:start:salary_talk"),
        ("🎓 Project Defense", "role:start:project_defense"),
    ]
    keyboard = []
    for i in range(0, len(scenarios), 2):
        row = [InlineKeyboardButton(text=scenarios[i][0], callback_data=scenarios[i][1])]
        if i + 1 < len(scenarios):
            row.append(InlineKeyboardButton(text=scenarios[i + 1][0], callback_data=scenarios[i + 1][1]))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="✏️ Своя ситуация", callback_data="role:custom")])
    keyboard.append([InlineKeyboardButton(text="❓ Что это?", callback_data="role:help")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="progress:workout_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def roleplay_active_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏁 Завершить", callback_data="role:finish")],
    ])


def settings_keyboard(user) -> InlineKeyboardMarkup:
    modes = {"aggressive": "⚡", "balanced": "🎯", "silent": "🤫", "teacher": "🎓"}
    mode_names = {"aggressive": "Агрессивный", "balanced": "Сбалансированный", "silent": "Тихий", "teacher": "Учитель"}
    current_mode = modes.get(user.correction_mode, "🎯")
    mode_name = mode_names.get(user.correction_mode, user.correction_mode.title())

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{current_mode} Режим: {mode_name}",
            callback_data="settings:mode",
        )],
        [InlineKeyboardButton(
            text=f"📊 Формальность: {'ВКЛ' if user.formality_meter else 'ВЫКЛ'}",
            callback_data="settings:formality",
        )],
        [InlineKeyboardButton(
            text=f"🌐 Тема: {user.topic_pack.title()}",
            callback_data="settings:topic",
        )],
        [InlineKeyboardButton(
            text=f"🔔 Уведомления: {'ВКЛ' if user.notifications else 'ВЫКЛ'}",
            callback_data="settings:notifications",
        )],
        [InlineKeyboardButton(text="💰 Расходы и баланс", callback_data="settings:usage")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")],
    ])


def correction_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Агрессивный", callback_data="settings:mode:aggressive")],
        [InlineKeyboardButton(text="🎯 Сбалансированный", callback_data="settings:mode:balanced")],
        [InlineKeyboardButton(text="🤫 Тихий", callback_data="settings:mode:silent")],
        [InlineKeyboardButton(text="🎓 Учитель", callback_data="settings:mode:teacher")],
        [InlineKeyboardButton(text="❓ Что это?", callback_data="settings:mode:help")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings:back")],
    ])


def topic_pack_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌐 Общий", callback_data="settings:topic:general"),
            InlineKeyboardButton(text="💻 IT", callback_data="settings:topic:it"),
        ],
        [
            InlineKeyboardButton(text="💼 Бизнес", callback_data="settings:topic:business"),
            InlineKeyboardButton(text="✈️ Путешествия", callback_data="settings:topic:travel"),
        ],
        [
            InlineKeyboardButton(text="🏥 Медицина", callback_data="settings:topic:medicine"),
            InlineKeyboardButton(text="🎮 Игры", callback_data="settings:topic:gaming"),
        ],
        [InlineKeyboardButton(text="❓ Что это?", callback_data="settings:topic:help")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings:back")],
    ])


def vocab_review_keyboard(word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👀 Показать ответ", callback_data=f"vocab:show:{word_id}")],
    ])


def vocab_answer_keyboard(word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Помню ✅", callback_data=f"vocab:yes:{word_id}"),
            InlineKeyboardButton(text="Не помню ❌", callback_data=f"vocab:no:{word_id}"),
        ],
    ])


def translation_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Ещё фразу", callback_data="workout:translation"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="menu"),
        ],
    ])


def explain_save_keyboard(breakdown: list[dict]) -> InlineKeyboardMarkup | None:
    """Inline buttons to save words from word_breakdown to vocabulary."""
    if not breakdown:
        return None
    buttons = []
    for i, w in enumerate(breakdown[:5]):
        word = w.get("word", "")
        if word:
            buttons.append([InlineKeyboardButton(
                text=f"➕ {word}",
                callback_data=f"vocab:explain_save:{i}",
            )])
    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


def correction_vocab_keyboard(word: str) -> InlineKeyboardMarkup:
    """Button to save the corrected word to vocabulary."""
    safe_word = word[:40].strip()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"➕ В словарь: {safe_word}", callback_data=f"word:add:{safe_word}")],
    ])


def vocab_reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📚 Да, давай", callback_data="vocab:start_review"),
            InlineKeyboardButton(text="⏰ Не сейчас", callback_data="vocab:remind_later"),
        ],
    ])


def grammar_map_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="progress:grammar_map")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="progress:back")],
    ])


def mistakes_keyboard(page: int = 0, total_pages: int = 1) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📅 Сегодня", callback_data="mistakes:today:0"),
            InlineKeyboardButton(text="📅 Неделя", callback_data="mistakes:week:0"),
        ],
        [
            InlineKeyboardButton(text="📅 Месяц", callback_data="mistakes:month:0"),
            InlineKeyboardButton(text="📅 Все", callback_data="mistakes:all:0"),
        ],
        [
            InlineKeyboardButton(text="📊 По категориям", callback_data="mistakes:categories:0"),
            InlineKeyboardButton(text="🔄 Повторяющиеся", callback_data="mistakes:repeated:0"),
        ],
    ]
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"mistakes:page:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"mistakes:page:{page + 1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
