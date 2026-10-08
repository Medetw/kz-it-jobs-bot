"""Parsers package — exports the unified fetch interface."""
from __future__ import annotations

from .habr_parser import HabrParser
from .hh_parser import HHParser
from .linkedin import extract_linkedin_urls
from .telegram_parser import TelegramChannelParser

__all__ = [
    "HHParser",
    "HabrParser",
    "TelegramChannelParser",
    "extract_linkedin_urls",
]
