# personal-english-mentor

Telegram bot for learning English. Checks grammar in real time, explains mistakes, helps with translations and pronunciation.

Works in two modes:
- **Regular bot** — commands and buttons in DMs
- **Business Mode** — connects to Telegram Business and checks messages in your real conversations

## Features

| Feature | Description |
|---------|-------------|
| **Auto grammar check** | In Business Mode, checks every message. Free pre-check via LanguageTool API, then GPT for detailed analysis if errors found |
| **Manual check** | Reply `?` to your own message — bot deletes `?`, checks grammar + naturalness, fixes the original and sends explanation to DMs |
| **AI Chat** | Free-form chat about English. Grammar, rules, word differences |
| **How to say** | Enter a phrase in Russian → get English variants (casual, formal, slang) |
| **Word** | Translation, synonyms, examples, collocations |
| **What did they mean** | Explain phrases, slang, idioms |
| **Roleplay** | Role-based dialogues (job interview, restaurant, airport, etc.) with grading |
| **Voice** | Pronunciation analysis, American accent scoring |
| **Workouts** | Exercises based on your mistakes |
| **Level test** | A1–C2 |
| **Vocabulary** | Save words + spaced repetition (Leitner system) |
| **Progress** | Stats, streaks, XP, levels |

## How Business Mode checking works

```
Message in any chat
  ↓
Filters (instant, free):
  too short? not English? "ok/thanks/lol"? → skip
  ↓
LanguageTool API (free, ~0.5 sec):
  no errors → skip, +XP
  errors found ↓
  ↓
GPT-4o-mini (~$0.001, ~3-5 sec):
  → fixes the original message in chat
  → sends detailed explanation to bot DMs
```

Manual check:
```
Reply "?" to your own message
  ↓
Bot deletes "?" → GPT checks grammar + naturalness
  → fixes original → explanation in DMs
```

~90% of messages are filtered for free. GPT is only called when there are actual errors.

## Requirements

- **Python 3.9+**
- **Telegram Bot Token** — [@BotFather](https://t.me/BotFather)
- **OpenAI-compatible API key** — for GPT and Whisper

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
3. The bot will start checking your messages in conversations

### Checking via "?"

In any business chat, reply `?` to your own message. The bot will:
1. Delete the `?`
2. Check grammar and naturalness
3. Fix the original message if there are errors
4. Send a detailed explanation to bot DMs

## Project structure

```
bot/
├── main.py                  # Entry point
├── config.py                # Config, XP, levels
├── db/
│   ├── database.py          # SQLite via SQLAlchemy async
│   └── models.py            # Models
├── handlers/
│   ├── business.py          # Business Mode — auto-check and manual
│   ├── commands.py          # /start, /stats, /settings, menu
│   ├── ai_chat.py           # AI chat about English
│   ├── check.py             # Text checking
│   ├── howtosay.py          # RU→EN translation with variants
│   ├── words.py             # Word info
│   ├── meaning.py           # Phrase/slang explanation
│   ├── roleplay.py          # Role-based dialogues
│   ├── voice.py             # Pronunciation analysis
│   ├── workout.py           # Mistake-based exercises
│   ├── translate.py         # Auto-translate RU↔EN
│   ├── callbacks.py         # Inline buttons
│   └── inline_query.py      # Inline mode
├── keyboards/
│   └── inline.py            # Keyboards
├── services/
│   ├── groq_client.py       # OpenAI API client (GPT + Whisper)
│   ├── grammar.py           # Correction formatting
│   ├── local_grammar.py     # LanguageTool API (free pre-check)
│   ├── gamification.py      # XP, streaks, levels
│   ├── stats.py             # User statistics
│   ├── vocabulary.py        # Vocabulary + Leitner
│   └── digest.py            # Error digest
└── utils/
    ├── prompts.py           # System prompts for GPT
    └── auth.py              # Auth
```

## Cost

| Action | Cost |
|--------|------|
| Filters + LanguageTool | Free |
| Message with error (GPT) | ~$0.001 |
| Voice message (Whisper + GPT) | ~$0.005 |
| **100 messages/day** | **~$0.50–1.00/mo** |

LanguageTool API filters ~60–80% of messages for free. GPT is only called for actual errors.

## Privacy

- **LanguageTool API** — texts are sent to `api.languagetool.org` for checking. [They don't store texts](https://languagetool.org/privacy/)
- **OpenAI API** — texts are processed by your chosen provider. Via API, [data is not used for training](https://openai.com/enterprise-privacy/)
- **Database** — stored locally (SQLite). Errors, stats, vocabulary — all on your server
- The bot only sees messages from business chats, nothing is forwarded to third parties

## Known limitations

- **Reactions in Business Mode** — Telegram Bot API doesn't support `message_reaction` in business chats. Use `?` reply as an alternative
- **LanguageTool API** — free public API, limit 20 requests/minute. Enough for personal use. On API failure, messages are automatically sent to GPT
- **Short phrases** — LanguageTool is bad at catching errors in short phrases (2-3 words). Use `?` for manual checking
- **SQLite** — for single user. For multiple users — use PostgreSQL
- **Russian UI** — bot prompts and explanations are in Russian (designed for Russian-speaking learners)

## Possible improvements

- [ ] PostgreSQL for multiple users
- [ ] Check caching (don't re-check identical phrases)
- [ ] Webhook instead of polling
- [ ] GPT rate limiting per user
- [ ] Multi-language UI support
- [ ] Error and vocabulary export

## Environment variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `PROXYAPI_KEY` | API key (OpenAI-compatible) |
| `DATABASE_URL` | Database URL (default: `sqlite+aiosqlite:///english_buddy.db`) |

## License

MIT
