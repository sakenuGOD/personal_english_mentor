# personal-english-mentor

Telegram bot for learning English. Checks grammar in real time, explains mistakes, builds vocabulary, tracks progress, and runs daily exercises.

Works in two modes:
- **Regular bot** — commands and buttons in DMs
- **Business Mode** — connects to Telegram Business and checks messages in real conversations

## Features

| Feature | Description |
|---------|-------------|
| **Auto grammar check** | Business Mode: checks every message automatically. LanguageTool pre-check (free) → GPT if errors found |
| **Manual check** | Reply `?` to your own message → bot deletes `?`, checks grammar + naturalness, fixes original, sends explanation to DMs |
| **Partner analysis** | Reply `?` to someone else's message → translation + meaning + tone + word breakdown + suggested replies |
| **AI Chat** | Free-form English conversation. Grammar questions, word differences, language rules |
| **How to say** | Russian phrase → English variants (casual, formal, slang) |
| **Word** | Translation, synonyms, examples, collocations, save to vocabulary |
| **What did they mean** | Explain phrases, slang, idioms from any message |
| **Manual text check** | Full grammar + naturalness review with detailed explanation |
| **Roleplay** | Scenario-based dialogues (job interview, doctor, airport, salary negotiation, etc.) with voice support and A–F grading |
| **Daily challenge** | Fill-in-the-blank grammar exercise, sent daily +30 XP |
| **Phrase of the day** | Daily idiom or colloquial phrase with origin, examples, usage tips |
| **Topic test** | Describe a topic → bot generates a custom multiple-choice quiz (5/10/15 questions) |
| **Workout** | Exercises based on your logged errors, translation challenges, general grammar |
| **Level test** | A1–C2 placement test |
| **Vocabulary** | Save words, spaced repetition via Leitner system (boxes 1–5) |
| **Error log** | Full mistake history with filters: today / week / month / all / by category / repeated. Keyword search |
| **Grammar map** | Visual map of all grammar constructions you've used |
| **Weekly insights** | Sunday digest: error trends, progress vs last week |
| **Progress & XP** | Streaks, XP, levels, error rate, stats |
| **Achievements** | Unlockable badges for milestones (error-free streaks, vocabulary size, etc.) |
| **Voice messages** | Forward voice → transcription + meaning/translation |
| **Formality meter** | Optional indicator of how formal/casual your English sounds |

## How grammar checking works

```
Message in any chat
  ↓
Filters (instant, free):
  too short? not English? "ok/thanks/lol"? → skip
  ↓
Pattern checker (instant):
  ESL-specific patterns (wrong prepositions, much/many, ed/ing confusion, etc.)
  errors found → GPT
  ↓
LanguageTool API (free, ~100ms):
  GRAMMAR/SEMANTICS category errors → GPT
  TYPOS only (contractions) → skip, +XP
  ↓
GPT-4o-mini (~$0.001, ~2-4 sec):
  → fixes original message in chat
  → sends detailed explanation to bot DMs
```

Manual check:
```
Reply "?" to your own message
  → bot deletes "?"
  → GPT checks grammar + naturalness regardless of gate
  → fixes original → explanation in DMs

Reply "?" to partner's message
  → translation + meaning + tone + word breakdown + how to reply
```

~85–90% of messages are filtered for free. GPT is only called when there are real errors.

## Workout modes

| Mode | Description |
|------|-------------|
| **Daily challenge** | Fill-in-the-blank sent every morning based on your weak categories |
| **Test by mistakes** | Quiz generated from your actual logged errors |
| **General training** | Mixed grammar exercises |
| **Translation challenge** | Translate Russian phrase to English — AI evaluates naturalness + grammar |
| **Level test** | Full A1–C2 placement |
| **Roleplay** | Scenario dialogue with voice support, hints, A–F grade + per-message breakdown |
| **Topic test** | Describe any topic → custom multiple-choice quiz |

## Requirements

- **Python 3.9+**
- **Telegram Bot Token** — [@BotFather](https://t.me/BotFather)
- **OpenAI-compatible API key** — for GPT and Whisper
- **LanguageTool** — free public API (no key needed) or self-hosted

### API provider

The bot uses an OpenAI-compatible API. Any provider works — just change `OPENAI_BASE_URL` and model in `bot/config.py`:

```python
# ProxyAPI (default)
OPENAI_BASE_URL = "https://api.proxyapi.ru/openai/v1"
OPENAI_MODEL = "gpt-4o-mini"

# OpenAI directly
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = "gpt-4o-mini"

# Any compatible provider
OPENAI_BASE_URL = "https://your-provider.com/v1"
OPENAI_MODEL = "your-model"
```

## Installation

### Local

```bash
git clone https://github.com/sakenuGOD/personal_english_mentor.git
cd personal_english_mentor

pip install -r requirements.txt

cp .env.example .env
# Fill in .env with your keys

python -m bot.main
```

### Docker

```bash
cp .env.example .env
# Fill in .env

docker-compose up -d
```

## Telegram Business setup

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. In Telegram: **Settings → Telegram Business → Chatbots** → connect your bot
3. The bot will start checking your messages in all conversations

### Checking via "?"

In any business chat, reply `?` to a message:
- **Your message** → grammar + naturalness check, fix original, explanation in DMs
- **Partner's message** → translation, meaning, tone, word breakdown, suggested replies

## Project structure

```
bot/
├── main.py                  # Entry point
├── config.py                # Config, XP values, levels
├── db/
│   ├── database.py          # SQLite via SQLAlchemy async + migrations
│   └── models.py            # User, Message, Error, Vocabulary, GrammarUsage, RoleplaySession
├── handlers/
│   ├── business.py          # Business Mode — auto-check, manual "?", partner analysis
│   ├── commands.py          # /start, /stats, /mistakes, /settings, /vocab, menu
│   ├── ai_chat.py           # AI chat about English
│   ├── check.py             # Manual text check
│   ├── howtosay.py          # RU→EN phrase variants
│   ├── words.py             # Word info + vocabulary save
│   ├── meaning.py           # Phrase/slang explanation
│   ├── roleplay.py          # Scenario dialogues with voice + grading
│   ├── workout.py           # Mistake-based exercises, level test, translation challenge
│   ├── translate.py         # Auto-translate RU↔EN
│   ├── callbacks.py         # Inline buttons, vocab review, daily challenge, topic test
│   └── inline_query.py      # Inline mode
├── keyboards/
│   └── inline.py            # All keyboards
├── services/
│   ├── groq_client.py       # OpenAI-compatible API client (GPT + Whisper)
│   ├── grammar.py           # GPT grammar check + correction formatting
│   ├── local_grammar.py     # LanguageTool + pattern checker (free gate)
│   ├── gamification.py      # XP, streaks, levels, achievements
│   ├── vocabulary.py        # Vocabulary CRUD + Leitner spaced repetition
│   ├── phrase_of_day.py     # Daily idiom generation + caching
│   ├── scheduler.py         # Daily phrase, daily challenge, vocab reminders, weekly insights
│   ├── stats.py             # User statistics
│   └── digest.py            # Weekly insights generation
└── utils/
    ├── prompts.py           # All GPT system prompts
    └── auth.py              # User access control
```

## Cost

| Action | Cost |
|--------|------|
| Filters + Pattern checker + LanguageTool | Free |
| Message with error (GPT) | ~$0.001 |
| Manual check / Phrase analysis | ~$0.001 |
| Voice message (Whisper + GPT) | ~$0.005 |
| Daily challenge / Phrase of day | ~$0.001 |
| **100 messages/day** | **~$0.50–1.00/mo** |

~85–90% of messages are pre-filtered for free. GPT only runs on real errors.

## Privacy

- **LanguageTool API** — texts sent to `api.languagetool.org`. [They don't store texts](https://languagetool.org/privacy/)
- **OpenAI API** — processed by your chosen provider. Via API, [data is not used for training](https://openai.com/enterprise-privacy/)
- **Database** — SQLite stored locally on your server. All errors, stats, vocabulary stay on your machine
- Bot only sees messages from business chats where you explicitly connected it

## Access control

By default, the bot is restricted to specific users. Edit `ALLOWED_USERS` in `bot/config.py`:

```python
# Only these user IDs can use the bot
ALLOWED_USERS: set[int] = {123456789, 987654321}

# Empty set = everyone allowed
ALLOWED_USERS: set[int] = set()
```

To find a user's ID, send `/start` to [@userinfobot](https://t.me/userinfobot).

## Known limitations

- **Reactions in Business Mode** — Telegram Bot API doesn't support `message_reaction` in business chats. Use `?` reply instead
- **LanguageTool API** — free public API, ~20 req/min. Sufficient for personal use. On failure, falls back to GPT automatically
- **Context-dependent tense errors** — "I went vs I have gone" requires context GPT doesn't always have in single-message mode. Use manual `?` check for full analysis
- **SQLite** — designed for single user. For multiple users use PostgreSQL
- **Russian UI** — all explanations in Russian (designed for Russian-speaking learners)

## Environment variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `PROXYAPI_KEY` | API key (OpenAI-compatible) |
| `DATABASE_URL` | Database URL (default: `sqlite+aiosqlite:///english_buddy.db`) |

## License

MIT
