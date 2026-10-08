# 🇰🇿 Kazakhstan IT Jobs Bot

A **production-grade Telegram Bot** that aggregates IT jobs and internships in Kazakhstan from multiple sources, with automated classification, smart hashtagging, and HR contact extraction.

## Features

- 🤖 **Multi-source scraping**: HH.kz API, Habr Career RSS, Telegram public channels
- 🎯 **5 IT tracks**: Backend, Frontend, QA, Mobile, Data/DevOps
- 🏷️ **Smart hashtags**: Auto-generated `#junior`, `#remote`, `#almaty`, `#backend`, etc.
- 📇 **HR contact extraction**: Telegram handles, emails, phones, LinkedIn profiles
- 💬 **Interactive DMs**: `/filter`, `/latest` commands for personalized job feeds
- 🔧 **Admin tools**: `/check_now`, `/stats`
- 🐳 **Docker-ready**: Dockerfile + docker-compose included
- 🧪 **`--mock` mode**: End-to-end testing without network calls

## Project Structure

```
parser/
├── bot.py                  # Bot runner, scheduler, handlers
├── config.py               # Environment settings & track definitions
├── classifier.py           # Rule-based track classifier + hashtag generator
├── contact_extractor.py    # Regex HR contact extractor
├── database.py             # SQLite WAL store (JSON fallback)
├── formatter.py            # Telegram HTML card builder & keyboards
├── parsers/
│   ├── __init__.py
│   ├── hh_parser.py        # HH.kz / api.hh.ru async parser
│   ├── habr_parser.py      # Habr Career RSS parser
│   ├── telegram_parser.py  # t.me/s/{channel} web preview scraper
│   └── linkedin.py         # LinkedIn URL extractor & search builder
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## Quick Start

### 1. Clone & Configure

```bash
cp .env.example .env
# Edit .env — fill in BOT_TOKEN, TARGET_CHANNEL, ADMIN_IDS
```

### 2. Run with Docker (recommended)

```bash
docker-compose up -d --build
docker-compose logs -f
```

### 3. Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python bot.py
```

### 4. Test without network (mock mode)

```bash
python bot.py --mock
```

### 5. Single scrape cycle (cron)

```bash
python bot.py --once
# Or with mock:
python bot.py --once --mock
```

### Cron example (every 30 minutes)

```cron
*/30 * * * * cd /path/to/parser && python bot.py --once >> /var/log/itjobs.log 2>&1
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | **Required.** Telegram bot token from @BotFather |
| `TARGET_CHANNEL` | — | Channel/group username (e.g. `@my_jobs`) |
| `ADMIN_IDS` | — | Comma-separated Telegram user IDs for admin commands |
| `POLL_INTERVAL_MINUTES` | `30` | How often to poll all sources |
| `POST_DELAY_SECONDS` | `2.5` | Delay between channel posts (flood prevention) |
| `DB_PATH` | `jobs.db` | SQLite database path |
| `JSON_FALLBACK_PATH` | `jobs_fallback.json` | Fallback storage for network filesystems |

## Bot Commands

### User commands
| Command | Description |
|---|---|
| `/start` | Welcome message and help |
| `/filter` | Select preferred IT tracks and badges |
| `/latest` | Get 5 most recent matching vacancies |
| `/help` | Command reference |

### Admin commands
| Command | Description |
|---|---|
| `/check_now` | Force an immediate scraping cycle |
| `/stats` | Show database statistics |

## IT Tracks

| Track | Technologies |
|---|---|
| ⚙️ **Backend** | Python, Java, Go, C#/.NET, Node.js, PHP |
| 🖥️ **Frontend** | React, Vue, Angular, TypeScript, JavaScript |
| 🔍 **QA** | Manual QA, Selenium, Playwright, pytest |
| 📱 **Mobile** | iOS/Swift, Android/Kotlin, Flutter, React Native |
| 📊 **Data/DevOps** | Data Analytics, ML/AI, Docker, Kubernetes, Linux |

## Sample Post Format

```
★ СТАЖИРОВКА / JUNIOR

🎯 [Backend] Junior Python Developer
🏢 Kolesa Group | 📍 Алматы
💰 300 000 — 500 000 KZT (до налогов)

📋 Мы ищем Junior Python разработчика. Требования: Python, Django/FastAPI, PostgreSQL...

🔥 ПРЯМЫЕ КОНТАКТЫ HR:
👤 Анна Смирнова
💬 Telegram: @hr_anna
📧 Email: hr@example.kz
📞 +77001234567

#стажировка #junior #backend #python #almaty
```

## Data Sources

- **HH.kz** (`api.hh.ru`) — Full API with contact objects, salary data
- **Habr Career** — RSS feeds filtered by Kazakhstan + remote
- **Telegram** — Public channel web previews (no Telethon session required):
  - `@devkz_jobs`, `@astanahub_jobs`, `@kolesa_team`, `@it_jobs_kz`

## Tech Stack

- **Python 3.11+**
- **aiogram 3.x** — Telegram Bot framework
- **aiohttp** — Async HTTP client
- **feedparser** — RSS parsing
- **beautifulsoup4 + lxml** — HTML scraping
- **APScheduler** — Background job scheduler
- **SQLite WAL** — Persistent storage with automatic JSON fallback
