"""Telegram HTML card builder and inline keyboard generator."""
from __future__ import annotations

import html
import json
import logging
from typing import List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from classifier import ClassificationResult
from contact_extractor import ExtractedContacts, build_linkedin_search_url
from database import Vacancy

logger = logging.getLogger(__name__)

_MAX_DESC_LENGTH = 800   # characters before truncation


def _esc(text: str) -> str:
    """HTML-escape a string for safe Telegram HTML mode."""
    return html.escape(text or "", quote=False)


def _truncate(text: str, max_len: int = _MAX_DESC_LENGTH) -> str:
    """Truncate text to max_len, appending ellipsis if needed."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


def format_vacancy_card(
    vacancy: Vacancy,
    classification: ClassificationResult,
    contacts: ExtractedContacts,
) -> str:
    """Build a clean HTML Telegram post card for a vacancy.

    Args:
        vacancy: The canonical vacancy data model.
        classification: Result from classifier.classify().
        contacts: Extracted HR contacts.

    Returns:
        HTML-formatted string ready for Telegram's HTML parse mode.
    """
    lines: List[str] = []

    # ── Header badge ──────────────────────────────────────────────────────────
    badge = classification.level_badge
    lines.append(f"<b>{_esc(badge)}</b>")
    lines.append("")

    # ── Track & Role ──────────────────────────────────────────────────────────
    if classification.track:
        track_label = f"{classification.track.emoji} [{classification.track.name}]"
        lines.append(f"🎯 <b>{_esc(track_label)} {_esc(vacancy.title)}</b>")
    else:
        lines.append(f"🎯 <b>{_esc(vacancy.title)}</b>")

    # ── Company & Location ────────────────────────────────────────────────────
    company_str = _esc(vacancy.company) if vacancy.company else "Компания не указана"
    location_str = _esc(vacancy.location) if vacancy.location else ""
    remote_str = " 🌐 Удаленно" if classification.is_remote else ""

    if location_str:
        lines.append(f"🏢 <b>{company_str}</b> | 📍 {location_str}{remote_str}")
    else:
        lines.append(f"🏢 <b>{company_str}</b>{remote_str}")

    # ── Salary ────────────────────────────────────────────────────────────────
    salary_display = _esc(vacancy.salary) if vacancy.salary else "По договоренности"
    lines.append(f"💰 <b>{salary_display}</b>")
    lines.append("")

    # ── Description snippet ───────────────────────────────────────────────────
    if vacancy.description:
        snippet = _truncate(_clean_html(vacancy.description))
        lines.append(f"📋 {_esc(snippet)}")
        lines.append("")

    # ── HR Contacts block ─────────────────────────────────────────────────────
    if contacts.has_any:
        lines.append("🔥 <b>ПРЯМЫЕ КОНТАКТЫ HR:</b>")
        if contacts.recruiter_names:
            lines.append(f"👤 {_esc(', '.join(contacts.recruiter_names))}")
        if contacts.telegram_handles:
            handles_str = " ".join(
                f'<a href="https://t.me/{h.lstrip("@")}">{_esc(h)}</a>'
                for h in contacts.telegram_handles
            )
            lines.append(f"💬 Telegram: {handles_str}")
        if contacts.emails:
            emails_str = " | ".join(
                f'<a href="mailto:{_esc(e)}">{_esc(e)}</a>'
                for e in contacts.emails
            )
            lines.append(f"📧 Email: {emails_str}")
        if contacts.phones:
            phones_str = " | ".join(
                f'<a href="tel:{_esc(p)}">{_esc(p)}</a>'
                for p in contacts.phones
            )
            lines.append(f"📞 {phones_str}")
        if contacts.linkedin_urls:
            li_links = " | ".join(
                f'<a href="{_esc(u)}">LinkedIn профиль</a>'
                for u in contacts.linkedin_urls
            )
            lines.append(f"💼 {li_links}")
    else:
        # Fallback: Google search that surfaces direct LinkedIn HR profile pages
        li_search = build_linkedin_search_url(vacancy.company)
        lines.append(
            f'🔍 <a href="{_esc(li_search)}">Найти профили HR {_esc(vacancy.company)} в LinkedIn</a>'
        )

    lines.append("")

    # ── Hashtags ──────────────────────────────────────────────────────────────
    if vacancy.hashtags:
        lines.append(vacancy.hashtags)

    return "\n".join(lines)


def build_inline_keyboard(
    vacancy: Vacancy,
    contacts: ExtractedContacts,
) -> InlineKeyboardMarkup:
    """Build inline keyboard with up to 3 buttons.

    Buttons:
        1. Open vacancy URL
        2. Write to recruiter (if direct Telegram handle exists)
        3. Find HR on LinkedIn
    """
    builder = InlineKeyboardBuilder()

    # Button 1: Open vacancy
    if vacancy.url:
        builder.button(text="🔗 Открыть вакансию", url=vacancy.url)

    # Button 2: Write to recruiter via Telegram
    if contacts.primary_telegram:
        handle = contacts.primary_telegram.lstrip("@")
        builder.button(
            text=f"💬 Написать {contacts.primary_telegram}",
            url=f"https://t.me/{handle}",
        )

    # Button 3: Find HR profiles on LinkedIn (via Google site: search)
    li_url = build_linkedin_search_url(vacancy.company)
    builder.button(text="🔎 Найти HR в LinkedIn (профили)", url=li_url)

    builder.adjust(1)  # one button per row
    return builder.as_markup()


def format_stats_message(stats: dict) -> str:
    """Format /stats output as clean HTML."""
    lines = ["<b>📊 Статистика базы данных</b>", ""]
    lines.append(f"📦 Всего вакансий: <b>{stats.get('total', 0)}</b>")
    lines.append(f"✅ Опубликовано: <b>{stats.get('posted', 0)}</b>")
    lines.append(
        f"⏳ Ожидают публикации: "
        f"<b>{stats.get('total', 0) - stats.get('posted', 0)}</b>"
    )
    lines.append("")

    lines.append("<b>По трекам:</b>")
    track_labels = {
        "backend": "⚙️ Backend",
        "frontend": "🖥️ Frontend",
        "qa": "🔍 QA",
        "mobile": "📱 Mobile",
        "data_devops": "📊 Data/DevOps",
        "unknown": "❓ Без трека",
        "": "❓ Без трека",
    }
    for key, label in track_labels.items():
        count = stats.get(f"track_{key}", 0)
        if count:
            lines.append(f"  {label}: <b>{count}</b>")

    lines.append("")
    lines.append("<b>По источникам:</b>")
    for key in ("hh", "habr", "telegram"):
        count = stats.get(f"source_{key}", 0)
        if count:
            lines.append(f"  {key.upper()}: <b>{count}</b>")

    return "\n".join(lines)


def format_filter_menu() -> str:
    """Format the /filter track selection message."""
    return (
        "⚙️ <b>Выберите ваши IT-треки:</b>\n\n"
        "Используйте кнопки ниже, чтобы настроить какие вакансии вам присылать.\n"
        "Можно выбрать несколько треков."
    )


def build_filter_keyboard(current_tracks: List[str]) -> InlineKeyboardMarkup:
    """Build a filter selection inline keyboard showing current selections."""
    builder = InlineKeyboardBuilder()
    options = [
        ("backend", "⚙️ Backend"),
        ("frontend", "🖥️ Frontend"),
        ("qa", "🔍 QA"),
        ("mobile", "📱 Mobile"),
        ("data_devops", "📊 Data/DevOps"),
    ]
    for track_key, label in options:
        selected = "✅ " if track_key in current_tracks else ""
        builder.button(
            text=f"{selected}{label}",
            callback_data=f"filter:{track_key}",
        )
    builder.button(text="⭐ Только стажировки", callback_data="filter:junior_only")
    builder.button(text="🌐 Только удаленно", callback_data="filter:remote_only")
    builder.button(text="💾 Сохранить", callback_data="filter:save")
    builder.adjust(2, 2, 1, 1, 1)
    return builder.as_markup()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _clean_html(text: str) -> str:
    """Strip HTML tags from a string."""
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def contacts_from_vacancy(vacancy: Vacancy) -> ExtractedContacts:
    """Deserialize contacts from vacancy.contacts_json."""
    from contact_extractor import ExtractedContacts
    try:
        data = json.loads(vacancy.contacts_json or "{}")
        return ExtractedContacts(
            telegram_handles=data.get("telegram_handles", []),
            emails=data.get("emails", []),
            phones=data.get("phones", []),
            recruiter_names=data.get("recruiter_names", []),
            linkedin_urls=data.get("linkedin_urls", []),
        )
    except (json.JSONDecodeError, TypeError):
        return ExtractedContacts()
