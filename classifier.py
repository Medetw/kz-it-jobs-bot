"""Rule-based vacancy classifier: assigns IT track, level badges, and hashtags."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set

from config import (
    CITY_KEYWORDS,
    JUNIOR_KEYWORDS,
    REMOTE_KEYWORDS,
    TRACKS,
    Track,
)


@dataclass
class ClassificationResult:
    """Full classification output for a single vacancy."""
    track: Optional[Track] = None
    is_junior: bool = False
    is_remote: bool = False
    city_tags: List[str] = field(default_factory=list)
    tech_tags: List[str] = field(default_factory=list)
    all_hashtags: List[str] = field(default_factory=list)

    def build_hashtag_string(self) -> str:
        """Return space-joined hashtag string for posting."""
        return " ".join(self.all_hashtags)

    @property
    def level_badge(self) -> str:
        if self.is_junior:
            return "★ СТАЖИРОВКА / JUNIOR"
        return "💼 ВАКАНСИЯ"

    @property
    def level_emoji(self) -> str:
        return "⭐" if self.is_junior else "💼"


def _tokenize(text: str) -> str:
    """Lowercase and normalize text for keyword matching."""
    return text.lower()


def _text_contains(haystack: str, keywords: Set[str]) -> bool:
    """Check if any keyword appears in the normalized haystack."""
    for kw in keywords:
        if kw in haystack:
            return True
    return False


def classify(
    title: str,
    description: str = "",
    company: str = "",
    location: str = "",
) -> ClassificationResult:
    """Classify a vacancy into an IT track with badges and hashtags.

    Args:
        title: Vacancy title.
        description: Full vacancy description text.
        company: Company name (optional).
        location: Location/city string (optional).

    Returns:
        ClassificationResult with track, badges, and hashtag list.
    """
    combined = _tokenize(f"{title} {description} {location}")

    result = ClassificationResult()

    # ── Track detection (priority order matters) ──────────────────────────────
    best_track_key: Optional[str] = None
    best_score: int = 0

    for track_key, track in TRACKS.items():
        score = sum(1 for kw in track.keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_track_key = track_key

    if best_track_key and best_score > 0:
        result.track = TRACKS[best_track_key]

    # ── Junior / internship detection ─────────────────────────────────────────
    result.is_junior = _text_contains(combined, JUNIOR_KEYWORDS)

    # ── Remote detection ──────────────────────────────────────────────────────
    result.is_remote = _text_contains(combined, REMOTE_KEYWORDS)

    # ── City tags ─────────────────────────────────────────────────────────────
    seen_city_tags: Set[str] = set()
    for city_kw, city_tag in CITY_KEYWORDS.items():
        if city_kw in combined and city_tag not in seen_city_tags:
            seen_city_tags.add(city_tag)
            result.city_tags.append(city_tag)

    # ── Tech tags from matched track ──────────────────────────────────────────
    if result.track:
        for tech_tag in result.track.tech_tags:
            tech_kw = tech_tag.lstrip("#").lower()
            # Only include tech tag if keyword appears in text
            if tech_kw in combined or any(
                tech_kw in kw for kw in result.track.keywords if kw in combined
            ):
                result.tech_tags.append(tech_tag)

    # ── Assemble final hashtag list ───────────────────────────────────────────
    tags: List[str] = []

    if result.is_junior:
        tags.extend(["#стажировка", "#junior"])

    if result.track:
        tags.append(result.track.hashtag)

    tags.extend(result.tech_tags)

    if result.is_remote:
        tags.append("#remote")

    tags.extend(result.city_tags)

    # Deduplicate preserving order
    seen: Set[str] = set()
    result.all_hashtags = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            result.all_hashtags.append(tag)

    return result


def detect_tech_tags_from_text(text: str) -> List[str]:
    """Extract all recognizable technology hashtags from free text.

    Useful for supplementing track tech_tags with any extras found.
    """
    lower = text.lower()
    tech_map = {
        "python": "#python",
        "django": "#django",
        "fastapi": "#fastapi",
        "flask": "#flask",
        "java": "#java",
        "spring": "#spring",
        "golang": "#golang",
        "go ": "#golang",
        "node.js": "#nodejs",
        "nodejs": "#nodejs",
        "php": "#php",
        "laravel": "#laravel",
        "c#": "#dotnet",
        ".net": "#dotnet",
        "react": "#react",
        "vue": "#vue",
        "angular": "#angular",
        "typescript": "#typescript",
        "javascript": "#javascript",
        "swift": "#swift",
        "kotlin": "#kotlin",
        "flutter": "#flutter",
        "docker": "#docker",
        "kubernetes": "#kubernetes",
        "linux": "#linux",
        "aws": "#aws",
        "terraform": "#terraform",
        "postgresql": "#postgresql",
        "mysql": "#mysql",
        "mongodb": "#mongodb",
        "redis": "#redis",
        "kafka": "#kafka",
        "selenium": "#selenium",
        "playwright": "#playwright",
    }

    found: List[str] = []
    seen: Set[str] = set()
    for kw, tag in tech_map.items():
        if kw in lower and tag not in seen:
            seen.add(tag)
            found.append(tag)
    return found
