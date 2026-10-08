"""LinkedIn URL extractor and recruiter search link generator."""
from __future__ import annotations

import re
from typing import List

# ── Regex patterns ────────────────────────────────────────────────────────────

_RE_LINKEDIN_PROFILE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/([A-Za-z0-9\-_%]+)/?",
    re.IGNORECASE,
)

_RE_LINKEDIN_COMPANY = re.compile(
    r"https?://(?:www\.)?linkedin\.com/company/([A-Za-z0-9\-_%]+)/?",
    re.IGNORECASE,
)

_RE_LINKEDIN_JOBS = re.compile(
    r"https?://(?:www\.)?linkedin\.com/jobs/[^\s\"'<>]+",
    re.IGNORECASE,
)


def extract_linkedin_urls(text: str) -> List[str]:
    """Extract all LinkedIn profile URLs from text.

    Args:
        text: Vacancy description or any text block.

    Returns:
        List of unique LinkedIn profile URLs found.
    """
    found: List[str] = []
    seen: set = set()

    for m in _RE_LINKEDIN_PROFILE.finditer(text):
        url = m.group(0).rstrip("/")
        if url.lower() not in seen:
            seen.add(url.lower())
            found.append(url)

    return found


def extract_company_linkedin_urls(text: str) -> List[str]:
    """Extract LinkedIn company page URLs from text."""
    found: List[str] = []
    seen: set = set()
    for m in _RE_LINKEDIN_COMPANY.finditer(text):
        url = m.group(0).rstrip("/")
        if url.lower() not in seen:
            seen.add(url.lower())
            found.append(url)
    return found


def build_recruiter_search_url(company: str, city: str = "Kazakhstan") -> str:
    """Build a Google search URL that returns direct LinkedIn HR profile pages.

    Uses `site:linkedin.com/in` so every Google result is a direct link to
    a recruiter's LinkedIn profile page — no LinkedIn login wall.

    Args:
        company: Company name to search for.
        city: City/country filter (default: Kazakhstan).

    Returns:
        Google search URL string.
    """
    from urllib.parse import quote_plus
    query = f'site:linkedin.com/in "{company}" (recruiter OR HR OR "talent acquisition") {city}'
    return f"https://www.google.com/search?q={quote_plus(query)}"


def build_job_search_url(title: str, company: str = "") -> str:
    """Build a LinkedIn Jobs search URL for a given title and company.

    Args:
        title: Job title to search.
        company: Optional company name.

    Returns:
        LinkedIn Jobs search URL.
    """
    from urllib.parse import quote_plus
    query = f"{title} {company}".strip()
    return (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={quote_plus(query)}"
        f"&location=Kazakhstan"
        f"&f_TPR=r604800"   # Posted in the last week
    )
