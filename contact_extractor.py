"""Regex & NLP engine for extracting HR / recruiter contacts from vacancy text."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set


@dataclass
class ExtractedContacts:
    """Aggregated contacts found in a vacancy."""
    telegram_handles: List[str] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    recruiter_names: List[str] = field(default_factory=list)
    linkedin_urls: List[str] = field(default_factory=list)

    @property
    def has_any(self) -> bool:
        return bool(
            self.telegram_handles
            or self.emails
            or self.phones
            or self.recruiter_names
            or self.linkedin_urls
        )

    @property
    def primary_telegram(self) -> Optional[str]:
        return self.telegram_handles[0] if self.telegram_handles else None

    def merge(self, other: ExtractedContacts) -> None:
        """Merge contacts from another extraction result."""
        for attr in ("telegram_handles", "emails", "phones", "recruiter_names", "linkedin_urls"):
            existing: list = getattr(self, attr)
            for item in getattr(other, attr):
                if item not in existing:
                    existing.append(item)


# ── Stop-words for Telegram handles ──────────────────────────────────
# Common bot names, channel names, and email domain fragments to ignore
_TG_STOPWORDS: Set[str] = {
    "bot", "channel", "group", "chat", "admin", "support",
    "gmail", "mail", "yandex", "yahoo", "outlook", "hotmail",
    "inbox", "email", "test", "example", "hh", "headhunter",
    "telegram", "whatsapp", "viber",
    "devkz_jobs", "astanahub_jobs", "kolesa_team", "it_jobs_kz",
    "habr", "github", "gitlab", "bitbucket",
}

# ── Regex patterns ────────────────────────────────────────────────────

# Telegram: @username or t.me/username
_RE_TG_AT = re.compile(
    r"(?<!\w)@([A-Za-z][A-Za-z0-9_]{4,31})(?!\w)",
)
_RE_TG_LINK = re.compile(
    r"(?:https?://)?t\.me/([A-Za-z][A-Za-z0-9_]{4,31})(?:\b|$)",
    re.IGNORECASE,
)

# Email
_RE_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)

# Phone numbers (Kazakhstan +7, 8)
_RE_PHONE = re.compile(
    r"(?:\+7|8)[\s\-]?\(?[0-9]{3}\)?[\s\-]?[0-9]{3}[\s\-]?[0-9]{2}[\s\-]?[0-9]{2}",
)

# LinkedIn URLs
_RE_LINKEDIN = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?",
    re.IGNORECASE,
)

# Recruiter / HR name patterns (Russian)
_RE_RECRUITER_NAME = re.compile(
    r"(?:контактное\s+лицо|рекрутер|hr|менеджер по персоналу|hiring manager)"
    r"[:\s—\-]+([А-ЯЁA-Z][а-яёa-z]+(?:\s+[А-ЯЁA-Z][а-яёa-z]+){0,2})",
    re.IGNORECASE,
)


def _is_valid_tg_handle(handle: str) -> bool:
    """Check if a Telegram handle is likely a real person (not a bot/channel)."""
    lower = handle.lower()
    # Reject if it's in stopwords
    if lower in _TG_STOPWORDS:
        return False
    # Reject if it ends with 'bot'
    if lower.endswith("bot"):
        return False
    # Reject if it looks like a channel (all underscores, common prefixes)
    if lower.startswith(("channel_", "chat_", "group_")):
        return False
    return True


def _normalize_phone(raw: str) -> str:
    """Normalize a KZ phone to +7XXXXXXXXXX format."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if not digits.startswith("7"):
        digits = "7" + digits
    return f"+{digits}"


def extract_contacts(text: str) -> ExtractedContacts:
    """Extract all HR / recruiter contacts from a block of text.

    Args:
        text: Raw vacancy description, contacts section, or combined text.

    Returns:
        ExtractedContacts with all found contact information.
    """
    result = ExtractedContacts()

    if not text:
        return result

    # ── Telegram handles ──────────────────────────────────────────────
    seen_tg: Set[str] = set()
    for match in _RE_TG_AT.finditer(text):
        handle = match.group(1)
        if _is_valid_tg_handle(handle) and handle.lower() not in seen_tg:
            seen_tg.add(handle.lower())
            result.telegram_handles.append(f"@{handle}")

    for match in _RE_TG_LINK.finditer(text):
        handle = match.group(1)
        if _is_valid_tg_handle(handle) and handle.lower() not in seen_tg:
            seen_tg.add(handle.lower())
            result.telegram_handles.append(f"@{handle}")

    # ── Emails ────────────────────────────────────────────────────────
    seen_emails: set[str] = set()
    for match in _RE_EMAIL.finditer(text):
        email = match.group(0).lower()
        if email not in seen_emails:
            seen_emails.add(email)
            result.emails.append(email)
    # ── Phones ────────────────────────────────────────────────────────
    seen_phones: set[str] = set()
    for match in _RE_PHONE.finditer(text):
        normalized = _normalize_phone(match.group(0))
        if normalized not in seen_phones:
            seen_phones.add(normalized)
            result.phones.append(normalized)

    # ── LinkedIn ──────────────────────────────────────────────────────
    seen_li: set[str] = set()
    for match in _RE_LINKEDIN.finditer(text):
        url = match.group(0).rstrip("/")
        if url.lower() not in seen_li:
            seen_li.add(url.lower())
            result.linkedin_urls.append(url)

    # ── Recruiter names ───────────────────────────────────────────────
    for match in _RE_RECRUITER_NAME.finditer(text):
        name = match.group(1).strip()
        if name and name not in result.recruiter_names and len(name) > 2:
            result.recruiter_names.append(name)

    return result


def build_linkedin_search_url(company: str, role: str = "recruiter") -> str:
    """Build a Google search URL that returns direct LinkedIn profile pages for a company's HR.

    Uses `site:linkedin.com/in` operator so results are direct profile links,
    not LinkedIn's own gated search page.

    Args:
        company: Company name.
        role: Role keyword (default: 'recruiter').

    Returns:
        Google search URL whose results are direct linkedin.com/in/... profile links.
    """
    from urllib.parse import quote_plus
    # site:linkedin.com/in restricts Google to only return profile pages
    query = f'site:linkedin.com/in "{company}" (recruiter OR HR OR "talent acquisition") Kazakhstan'
    return f"https://www.google.com/search?q={quote_plus(query)}"
