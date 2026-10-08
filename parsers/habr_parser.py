"""Habr Career RSS parser for Kazakhstan IT vacancies."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, List, Optional
from urllib.parse import quote_plus

import aiohttp
import feedparser

from config import HABR_REQUEST_DELAY, HABR_RSS_URL
from contact_extractor import extract_contacts
from database import Vacancy

logger = logging.getLogger(__name__)

_HABR_SEARCH_URLS = [
    HABR_RSS_URL,
    # Additional query-based RSS feeds for broader coverage
    f"https://career.habr.com/vacancies/rss?q=Junior&type=all&country_id=64",
    f"https://career.habr.com/vacancies/rss?q=Internship&type=all&country_id=64",
    f"https://career.habr.com/vacancies/rss?q=стажировка&type=all&country_id=64",
    f"https://career.habr.com/vacancies/rss?q=remote+Kazakhstan&type=all",
]

_HEADERS = {
    "User-Agent": "KazakhstanITJobsBot/1.0 (feedparser)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}


class HabrParser:
    """Fetch IT vacancies from Habr Career RSS feeds."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        mock: bool = False,
    ):
        self._session = session
        self._mock = mock
        self._owns_session = session is None

    async def __aenter__(self) -> "HabrParser":
        if self._owns_session:
            self._session = aiohttp.ClientSession(headers=_HEADERS)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._owns_session and self._session:
            await self._session.close()

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_all(self) -> List[Vacancy]:
        """Fetch vacancies from all Habr RSS feeds."""
        if self._mock:
            return _mock_vacancies()

        vacancies: List[Vacancy] = []
        seen_ids: set = set()

        for feed_url in _HABR_SEARCH_URLS:
            batch = await self._fetch_feed(feed_url)
            for v in batch:
                if v.source_id not in seen_ids:
                    seen_ids.add(v.source_id)
                    vacancies.append(v)
            await asyncio.sleep(HABR_REQUEST_DELAY)

        logger.info("HabrParser fetched %d unique vacancies", len(vacancies))
        return vacancies

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _fetch_feed(self, url: str) -> List[Vacancy]:
        """Fetch and parse a single RSS feed URL."""
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    logger.warning("Habr RSS returned %s for %s", resp.status, url)
                    return []
                raw = await resp.text()
        except Exception as exc:
            logger.error("Habr RSS fetch error for %s: %s", url, exc)
            return []

        feed = feedparser.parse(raw)
        if feed.bozo and not feed.entries:
            logger.warning("Habr RSS parse error for %s", url)
            return []

        vacancies: List[Vacancy] = []
        for entry in feed.entries:
            v = _entry_to_vacancy(entry)
            if v:
                vacancies.append(v)
        return vacancies


# ── Conversion helpers ────────────────────────────────────────────────────────

def _entry_to_vacancy(entry: Any) -> Optional[Vacancy]:
    """Convert a feedparser entry to a Vacancy."""
    try:
        entry_id = entry.get("id") or entry.get("link", "")
        if not entry_id:
            return None

        source_id = f"habr_{_hash_id(entry_id)}"
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        summary = entry.get("summary", "") or entry.get("description", "")

        # Extract company from tags or summary
        company = _extract_company(entry)
        location = _extract_location(entry)

        # Extract contacts from description
        contacts = extract_contacts(summary)
        contacts_json = json.dumps({
            "telegram_handles": contacts.telegram_handles,
            "emails": contacts.emails,
            "phones": contacts.phones,
            "recruiter_names": contacts.recruiter_names,
            "linkedin_urls": contacts.linkedin_urls,
        }, ensure_ascii=False)

        return Vacancy(
            source_id=source_id,
            source="habr",
            title=title,
            company=company,
            location=location,
            description=summary,
            url=link,
            salary=_extract_salary(entry),
            contacts_json=contacts_json,
        )
    except Exception as exc:
        logger.debug("Habr entry parse error: %s", exc)
        return None


def _hash_id(url: str) -> str:
    """Generate a short stable ID from a URL."""
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _extract_company(entry: Any) -> str:
    """Try to extract company name from entry tags or author field."""
    author = getattr(entry, "author", "") or ""
    if author:
        return author.strip()
    for tag in getattr(entry, "tags", []):
        term = tag.get("term", "")
        if term and not term.startswith("#"):
            return term
    return ""


def _extract_location(entry: Any) -> str:
    """Try to find location in entry content."""
    for tag in getattr(entry, "tags", []):
        term = tag.get("term", "").lower()
        if any(city in term for city in ["алматы", "астана", "казахстан", "almaty", "astana"]):
            return tag.get("term", "")
    return "Казахстан"


def _extract_salary(entry: Any) -> str:
    """Try to extract salary info from entry."""
    summary = entry.get("summary", "") or ""
    import re
    # Match patterns like "300 000 — 500 000 KZT" or "$1000-2000"
    m = re.search(
        r"(\d[\d\s]*(?:—|-)\s*\d[\d\s]*\s*(?:KZT|тенге|₸|\$|USD))",
        summary,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


# ── Mock data ─────────────────────────────────────────────────────────────────

def _mock_vacancies() -> List[Vacancy]:
    return [
        Vacancy(
            source_id="habr_mock_001",
            source="habr",
            title="Data Scientist (Junior)",
            company="Freedom Finance",
            location="Алматы / Удаленно",
            description=(
                "Ищем Junior Data Scientist. Требования: Python, pandas, sklearn.\n"
                "Стажировка приветствуется. HR: jobs@freedom.kz"
            ),
            url="https://career.habr.com/vacancies/123456",
            salary="400 000 — 600 000 KZT",
            track="data_devops",
            is_junior=True,
            is_remote=True,
            contacts_json=json.dumps({
                "telegram_handles": [],
                "emails": ["jobs@freedom.kz"],
                "phones": [],
                "recruiter_names": [],
                "linkedin_urls": [],
            }),
        ),
        Vacancy(
            source_id="habr_mock_002",
            source="habr",
            title="DevOps Engineer",
            company="Halyk Bank",
            location="Алматы",
            description=(
                "Нужен DevOps инженер. Docker, Kubernetes, CI/CD, Linux.\n"
                "Опыт от 2 лет."
            ),
            url="https://career.habr.com/vacancies/234567",
            salary="800 000 — 1 200 000 KZT",
            track="data_devops",
            contacts_json="{}",
        ),
    ]
