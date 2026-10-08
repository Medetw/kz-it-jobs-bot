"""HeadHunter Kazakhstan (hh.kz / api.hh.ru) async parser."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp

from config import (
    HH_AREA_ALMATY,
    HH_AREA_ASTANA,
    HH_AREA_KAZAKHSTAN,
    HH_BASE_URL,
    HH_EXPERIENCE_FILTERS,
    HH_PER_PAGE,
    HH_REQUEST_DELAY,
    HH_SEARCH_QUERIES,
)
from contact_extractor import ExtractedContacts, extract_contacts
from database import Vacancy

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "KazakhstanITJobsBot/1.0 (support@example.com)",
    "Accept": "application/json",
    "HH-User-Agent": "KazakhstanITJobsBot/1.0 (support@example.com)",
}


class HHParser:
    """Fetch IT vacancies from HeadHunter Kazakhstan API."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        areas: Optional[List[int]] = None,
        mock: bool = False,
    ):
        self._session = session
        self._areas = areas or [HH_AREA_KAZAKHSTAN]
        self._mock = mock
        self._owns_session = session is None

    async def __aenter__(self) -> "HHParser":
        if self._owns_session:
            self._session = aiohttp.ClientSession(headers=_HEADERS)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._owns_session and self._session:
            await self._session.close()

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_all(self) -> List[Vacancy]:
        """Fetch vacancies for all tracks and experience levels."""
        if self._mock:
            return _mock_vacancies()

        vacancies: List[Vacancy] = []
        seen_ids: set = set()

        for track_key, queries in HH_SEARCH_QUERIES.items():
            for query in queries:
                for experience in HH_EXPERIENCE_FILTERS:
                    for area in self._areas:
                        batch = await self._fetch_search(
                            query=query,
                            experience=experience,
                            area=area,
                            track_key=track_key,
                        )
                        for v in batch:
                            if v.source_id not in seen_ids:
                                seen_ids.add(v.source_id)
                                vacancies.append(v)
                        await asyncio.sleep(HH_REQUEST_DELAY)

        logger.info("HHParser fetched %d unique vacancies", len(vacancies))
        return vacancies

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _fetch_search(
        self,
        query: str,
        experience: str,
        area: int,
        track_key: str,
    ) -> List[Vacancy]:
        """Run a single search query and return Vacancy list."""
        params = {
            "text": query,
            "area": area,
            "experience": experience,
            "per_page": HH_PER_PAGE,
            "page": 0,
            "only_with_salary": False,
        }
        url = f"{HH_BASE_URL}/vacancies?{urlencode(params)}"

        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning("HH search returned %s for query=%s", resp.status, query)
                    return []
                data = await resp.json()
        except Exception as exc:
            logger.error("HH search error for query=%s: %s", query, exc)
            return []

        items = data.get("items", [])
        vacancies: List[Vacancy] = []

        for item in items:
            v = _item_to_vacancy(item, track_key)
            # Optionally fetch full details for contacts
            detailed = await self._fetch_detail(item["id"])
            if detailed:
                v = _merge_detail(v, detailed)
            vacancies.append(v)
            await asyncio.sleep(HH_REQUEST_DELAY)

        return vacancies

    async def _fetch_detail(self, vacancy_id: str) -> Optional[Dict]:
        """Fetch full vacancy detail including contacts object."""
        url = f"{HH_BASE_URL}/vacancies/{vacancy_id}"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception as exc:
            logger.debug("HH detail fetch failed for id=%s: %s", vacancy_id, exc)
            return None


# ── Conversion helpers ────────────────────────────────────────────────────────

def _item_to_vacancy(item: Dict, track_key: str) -> Vacancy:
    """Convert a HH API search item to a Vacancy."""
    salary_str = _format_salary(item.get("salary"))
    area = item.get("area", {})
    employer = item.get("employer", {})

    return Vacancy(
        source_id=f"hh_{item['id']}",
        source="hh",
        title=item.get("name", ""),
        company=employer.get("name", ""),
        location=area.get("name", ""),
        description="",         # filled in detail fetch
        url=item.get("alternate_url", ""),
        salary=salary_str,
        track=track_key,
    )


def _merge_detail(v: Vacancy, detail: Dict) -> Vacancy:
    """Enrich vacancy with data from the detail endpoint."""
    # Description
    v.description = detail.get("description", "") or ""

    # Official contacts from HH API
    contacts_obj = detail.get("contacts") or {}
    extracted = ExtractedContacts()
    if contacts_obj:
        name = contacts_obj.get("name", "")
        if name:
            extracted.recruiter_names.append(name)
        for phone_entry in contacts_obj.get("phones", []):
            phone = phone_entry.get("formatted", "")
            if phone:
                extracted.phones.append(phone)
        email = contacts_obj.get("email", "")
        if email:
            extracted.emails.append(email)

    # Also run regex extractor on description text
    desc_contacts = extract_contacts(v.description)
    extracted.merge(desc_contacts)

    v.contacts_json = json.dumps({
        "telegram_handles": extracted.telegram_handles,
        "emails": extracted.emails,
        "phones": extracted.phones,
        "recruiter_names": extracted.recruiter_names,
        "linkedin_urls": extracted.linkedin_urls,
    }, ensure_ascii=False)
    return v


def _format_salary(salary: Optional[Dict]) -> str:
    if not salary:
        return ""
    frm = salary.get("from")
    to = salary.get("to")
    currency = salary.get("currency", "KZT")
    gross = "(до налогов)" if salary.get("gross") else "(на руки)"

    if frm and to:
        return f"{frm:,} — {to:,} {currency} {gross}"
    elif frm:
        return f"от {frm:,} {currency} {gross}"
    elif to:
        return f"до {to:,} {currency} {gross}"
    return ""


# ── Mock data ─────────────────────────────────────────────────────────────────

def _mock_vacancies() -> List[Vacancy]:
    """Return realistic mock vacancies for --mock mode."""
    import json
    mock_contacts = json.dumps({
        "telegram_handles": ["@hr_anna"],
        "emails": ["hr@example.kz"],
        "phones": ["+77001234567"],
        "recruiter_names": ["Анна Смирнова"],
        "linkedin_urls": [],
    })
    return [
        Vacancy(
            source_id="hh_mock_001",
            source="hh",
            title="Junior Python Developer",
            company="Kolesa Group",
            location="Алматы",
            description=(
                "Мы ищем Junior Python разработчика.\n"
                "Требования: Python, Django/FastAPI, PostgreSQL.\n"
                "Стажировка возможна. Рекрутер: Анна Смирнова. "
                "Контакт: @hr_anna, hr@example.kz"
            ),
            url="https://hh.kz/vacancy/1234567",
            salary="300 000 — 500 000 KZT (до налогов)",
            track="backend",
            is_junior=True,
            contacts_json=mock_contacts,
        ),
        Vacancy(
            source_id="hh_mock_002",
            source="hh",
            title="Frontend Developer (React)",
            company="Kaspi.kz",
            location="Алматы",
            description=(
                "Ищем Frontend разработчика на React.\n"
                "Опыт: TypeScript, React, Redux. Удаленная работа."
            ),
            url="https://hh.kz/vacancy/2345678",
            salary="600 000 — 900 000 KZT (на руки)",
            track="frontend",
            is_remote=True,
            contacts_json="{}",
        ),
        Vacancy(
            source_id="hh_mock_003",
            source="hh",
            title="QA Engineer (Automation)",
            company="Jusan Bank",
            location="Астана",
            description=(
                "Вакансия QA автоматизатора. Selenium, Python, pytest.\n"
                "Опыт от 1 года."
            ),
            url="https://hh.kz/vacancy/3456789",
            salary="400 000 — 700 000 KZT (до налогов)",
            track="qa",
            contacts_json="{}",
        ),
    ]
