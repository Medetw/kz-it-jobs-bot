"""Telegram public channel web-preview scraper (no session/Telethon required)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, List, Optional
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup, Tag

from config import TELEGRAM_CHANNELS, TELEGRAM_PREVIEW_BASE, TELEGRAM_REQUEST_DELAY
from contact_extractor import extract_contacts
from database import Vacancy

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Minimum text length to consider a post as a vacancy
_MIN_POST_LENGTH = 100

# Keywords to filter posts likely related to IT jobs
_JOB_KEYWORDS = {
    "вакансия", "vacancy", "hiring", "работа", "job", "ищем", "требуется",
    "разработчик", "developer", "engineer", "программист", "стажировка",
    "intern", "junior", "middle", "senior", "qa", "devops", "frontend",
    "backend", "mobile", "данные", "data", "python", "java", "kotlin",
    "swift", "react", "flutter", "golang",
}


class TelegramChannelParser:
    """Scrape public Telegram channel web previews for IT job posts."""

    def __init__(
        self,
        channels: Optional[List[str]] = None,
        session: Optional[aiohttp.ClientSession] = None,
        mock: bool = False,
    ):
        self._channels = channels or TELEGRAM_CHANNELS
        self._session = session
        self._mock = mock
        self._owns_session = session is None

    async def __aenter__(self) -> "TelegramChannelParser":
        if self._owns_session:
            self._session = aiohttp.ClientSession(headers=_HEADERS)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._owns_session and self._session:
            await self._session.close()

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_all(self) -> List[Vacancy]:
        """Scrape all configured Telegram channels."""
        if self._mock:
            return _mock_vacancies()

        vacancies: List[Vacancy] = []
        seen_ids: set = set()

        for channel in self._channels:
            batch = await self._fetch_channel(channel)
            for v in batch:
                if v.source_id not in seen_ids:
                    seen_ids.add(v.source_id)
                    vacancies.append(v)
            await asyncio.sleep(TELEGRAM_REQUEST_DELAY)

        logger.info("TelegramParser fetched %d posts from %d channels",
                    len(vacancies), len(self._channels))
        return vacancies

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _fetch_channel(self, channel: str) -> List[Vacancy]:
        """Fetch and parse the web preview page of a single channel."""
        url = f"{TELEGRAM_PREVIEW_BASE}{channel}"
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    logger.warning("Telegram preview returned %s for %s", resp.status, channel)
                    return []
                html = await resp.text()
        except Exception as exc:
            logger.error("Telegram channel fetch error for %s: %s", channel, exc)
            return []

        return _parse_channel_html(html, channel)


# ── HTML parsing ──────────────────────────────────────────────────────────────

def _parse_channel_html(html: str, channel: str) -> List[Vacancy]:
    """Parse t.me/s/{channel} HTML and extract job posts."""
    soup = BeautifulSoup(html, "lxml")
    posts = soup.find_all("div", class_="tgme_widget_message")

    vacancies: List[Vacancy] = []
    for post in posts:
        v = _post_to_vacancy(post, channel)
        if v:
            vacancies.append(v)
    return vacancies


def _post_to_vacancy(post: Tag, channel: str) -> Optional[Vacancy]:
    """Convert a single Telegram post element to a Vacancy if it's job-related."""
    # Extract message ID from the link
    msg_link_tag = post.find("a", class_="tgme_widget_message_date")
    if not msg_link_tag:
        return None

    msg_url = msg_link_tag.get("href", "")
    msg_id = _extract_msg_id(msg_url)
    if not msg_id:
        return None

    source_id = f"tg_{channel}_{msg_id}"

    # Extract text content
    text_tag = post.find("div", class_="tgme_widget_message_text")
    if not text_tag:
        return None
    text = text_tag.get_text(separator="\n", strip=True)

    if len(text) < _MIN_POST_LENGTH:
        return None

    # Filter: must contain job-related keywords
    text_lower = text.lower()
    if not any(kw in text_lower for kw in _JOB_KEYWORDS):
        return None

    # Extract publication datetime
    time_tag = post.find("time")
    fetched_at = datetime.utcnow().isoformat()
    if time_tag and time_tag.get("datetime"):
        fetched_at = time_tag["datetime"]

    # Extract title from first non-empty line
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = lines[0][:120] if lines else "Вакансия"

    # Extract contacts from text
    contacts = extract_contacts(text)
    contacts_json = json.dumps({
        "telegram_handles": contacts.telegram_handles,
        "emails": contacts.emails,
        "phones": contacts.phones,
        "recruiter_names": contacts.recruiter_names,
        "linkedin_urls": contacts.linkedin_urls,
    }, ensure_ascii=False)

    return Vacancy(
        source_id=source_id,
        source="telegram",
        title=title,
        company=_channel_to_company(channel),
        location=_detect_location(text),
        description=text,
        url=msg_url,
        salary=_extract_salary(text),
        contacts_json=contacts_json,
        fetched_at=fetched_at,
    )


def _extract_msg_id(url: str) -> Optional[str]:
    m = re.search(r"/(\d+)$", url)
    return m.group(1) if m else None


def _channel_to_company(channel: str) -> str:
    mapping = {
        "devkz_jobs": "DevKZ",
        "astanahub_jobs": "Astana Hub",
        "kolesa_team": "Kolesa Group",
        "it_jobs_kz": "IT Jobs KZ",
    }
    return mapping.get(channel, f"@{channel}")


def _detect_location(text: str) -> str:
    lower = text.lower()
    locations = []
    if any(kw in lower for kw in ["алматы", "almaty", "алма-ата"]):
        locations.append("Алматы")
    if any(kw in lower for kw in ["астана", "astana", "нур-султан"]):
        locations.append("Астана")
    if any(kw in lower for kw in ["шымкент", "shymkent"]):
        locations.append("Шымкент")
    if any(kw in lower for kw in ["удаленно", "remote", "дистанционно"]):
        locations.append("Удаленно")
    return " / ".join(locations) if locations else "Казахстан"


def _extract_salary(text: str) -> str:
    m = re.search(
        r"(\d[\d\s]*(?:—|-)\s*\d[\d\s]*\s*(?:KZT|тенге|₸|\$|USD|usd))",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    m2 = re.search(r"(?:зп|зарплата|salary)[:\s]+([^\n]+)", text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()[:80]
    return ""


# ── Mock data ─────────────────────────────────────────────────────────────────

def _mock_vacancies() -> List[Vacancy]:
    return [
        Vacancy(
            source_id="tg_devkz_jobs_mock_001",
            source="telegram",
            title="Mobile Developer (Flutter) | Стажировка",
            company="DevKZ",
            location="Алматы / Удаленно",
            description=(
                "📱 Стажировка для Flutter разработчика!\n"
                "Колesa Group ищет стажера.\n"
                "Dart, Flutter, Firebase.\n"
                "Без опыта — мы обучим!\n"
                "Контакт: @hr_kolesa | hr@kolesa.kz\n"
                "#flutter #mobile #стажировка #almaty"
            ),
            url="https://t.me/devkz_jobs/12345",
            salary="150 000 — 250 000 KZT",
            track="mobile",
            is_junior=True,
            is_remote=True,
            contacts_json=json.dumps({
                "telegram_handles": ["@hr_kolesa"],
                "emails": ["hr@kolesa.kz"],
                "phones": [],
                "recruiter_names": [],
                "linkedin_urls": [],
            }),
        ),
        Vacancy(
            source_id="tg_astanahub_jobs_mock_001",
            source="telegram",
            title="Backend Developer (Node.js) — Astana Hub стартап",
            company="Astana Hub",
            location="Астана",
            description=(
                "🚀 Astana Hub startup hiring Backend Developer!\n"
                "Node.js, TypeScript, PostgreSQL, Docker.\n"
                "Опыт: от 1 года.\n"
                "Зарплата: 500 000 — 800 000 KZT.\n"
                "Контактное лицо: Мария Иванова\n"
                "Telegram: @startup_hr_maria\n"
                "#backend #nodejs #astana"
            ),
            url="https://t.me/astanahub_jobs/67890",
            salary="500 000 — 800 000 KZT",
            track="backend",
            contacts_json=json.dumps({
                "telegram_handles": ["@startup_hr_maria"],
                "emails": [],
                "phones": [],
                "recruiter_names": ["Мария Иванова"],
                "linkedin_urls": [],
            }),
        ),
    ]
