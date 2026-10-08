"""SQLite (WAL mode) persistent store with JSON fallback for network filesystems."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, Generator, List, Optional

from config import DB_PATH, JSON_FALLBACK_PATH

logger = logging.getLogger(__name__)


@dataclass
class Vacancy:
    """Canonical vacancy model shared across all modules."""
    source_id: str                        # unique key per source (e.g. "hh_123456")
    source: str                           # "hh", "habr", "telegram", etc.
    title: str
    company: str
    location: str
    description: str
    url: str
    salary: str = ""
    track: str = ""
    hashtags: str = ""                    # space-joined hashtag string
    is_junior: bool = False
    is_remote: bool = False
    contacts_json: str = "{}"             # JSON-serialized ExtractedContacts
    posted_to_channel: bool = False
    fetched_at: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )


@dataclass
class SubscriberPrefs:
    user_id: int
    tracks: List[str] = field(default_factory=list)   # e.g. ["backend", "mobile"]
    junior_only: bool = False
    remote_only: bool = False


# ── SQLite helpers ────────────────────────────────────────────────────────────

_CREATE_VACANCIES = """
CREATE TABLE IF NOT EXISTS vacancies (
    source_id          TEXT PRIMARY KEY,
    source             TEXT NOT NULL,
    title              TEXT NOT NULL,
    company            TEXT NOT NULL DEFAULT '',
    location           TEXT NOT NULL DEFAULT '',
    description        TEXT NOT NULL DEFAULT '',
    url                TEXT NOT NULL DEFAULT '',
    salary             TEXT NOT NULL DEFAULT '',
    track              TEXT NOT NULL DEFAULT '',
    hashtags           TEXT NOT NULL DEFAULT '',
    is_junior          INTEGER NOT NULL DEFAULT 0,
    is_remote          INTEGER NOT NULL DEFAULT 0,
    contacts_json      TEXT NOT NULL DEFAULT '{}',
    posted_to_channel  INTEGER NOT NULL DEFAULT 0,
    fetched_at         TEXT NOT NULL
);
"""

_CREATE_VACANCIES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_vac_source ON vacancies(source);",
    "CREATE INDEX IF NOT EXISTS idx_vac_track ON vacancies(track);",
    "CREATE INDEX IF NOT EXISTS idx_vac_posted ON vacancies(posted_to_channel);",
    "CREATE INDEX IF NOT EXISTS idx_vac_junior ON vacancies(is_junior);",
    "CREATE INDEX IF NOT EXISTS idx_vac_fetched ON vacancies(fetched_at);",
]

_CREATE_SUBSCRIBERS = """
CREATE TABLE IF NOT EXISTS subscribers (
    user_id     INTEGER PRIMARY KEY,
    tracks      TEXT NOT NULL DEFAULT '[]',
    junior_only INTEGER NOT NULL DEFAULT 0,
    remote_only INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    """Thread-safe SQLite database with WAL mode and JSON fallback."""

    def __init__(self, db_path: str = DB_PATH, json_path: str = JSON_FALLBACK_PATH):
        self._db_path = db_path
        self._json_path = json_path
        self._use_json = False
        self._json_store: Dict[str, dict] = {}
        self._init()

    # ── Initialization ────────────────────────────────────────────────────────

    def _init(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute("PRAGMA foreign_keys=ON;")
                conn.execute(_CREATE_VACANCIES)
                for idx_sql in _CREATE_VACANCIES_INDEXES:
                    conn.execute(idx_sql)
                conn.execute(_CREATE_SUBSCRIBERS)
            logger.info("SQLite database initialized at %s (WAL mode)", self._db_path)
        except sqlite3.OperationalError as exc:
            logger.warning(
                "SQLite init failed (%s) — falling back to JSON store at %s",
                exc,
                self._json_path,
            )
            self._use_json = True
            self._load_json()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── JSON fallback ─────────────────────────────────────────────────────────

    def _load_json(self) -> None:
        if os.path.exists(self._json_path):
            try:
                with open(self._json_path, "r", encoding="utf-8") as f:
                    self._json_store = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._json_store = {}

    def _save_json(self) -> None:
        with open(self._json_path, "w", encoding="utf-8") as f:
            json.dump(self._json_store, f, ensure_ascii=False, indent=2)

    # ── Vacancy CRUD ──────────────────────────────────────────────────────────

    def is_seen(self, source_id: str) -> bool:
        """Return True if vacancy was already stored (deduplication)."""
        if self._use_json:
            return source_id in self._json_store
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM vacancies WHERE source_id = ?", (source_id,)
            ).fetchone()
            return row is not None

    def save_vacancy(self, v: Vacancy) -> bool:
        """Persist a vacancy. Returns False if already exists (duplicate)."""
        if self.is_seen(v.source_id):
            return False

        if self._use_json:
            self._json_store[v.source_id] = asdict(v)
            self._save_json()
            return True

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO vacancies
                    (source_id, source, title, company, location, description,
                     url, salary, track, hashtags, is_junior, is_remote,
                     contacts_json, posted_to_channel, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    v.source_id, v.source, v.title, v.company, v.location,
                    v.description, v.url, v.salary, v.track, v.hashtags,
                    int(v.is_junior), int(v.is_remote), v.contacts_json,
                    int(v.posted_to_channel), v.fetched_at,
                ),
            )
        return True

    def mark_posted(self, source_id: str) -> None:
        """Mark a vacancy as posted to channel."""
        if self._use_json:
            if source_id in self._json_store:
                self._json_store[source_id]["posted_to_channel"] = True
                self._save_json()
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE vacancies SET posted_to_channel = 1 WHERE source_id = ?",
                (source_id,),
            )

    def get_unposted(self, limit: int = 20) -> List[Vacancy]:
        """Fetch vacancies not yet posted to the channel, newest first."""
        if self._use_json:
            items = [
                v for v in self._json_store.values()
                if not v.get("posted_to_channel")
            ]
            items.sort(key=lambda x: x.get("fetched_at", ""), reverse=True)
            return [Vacancy(**v) for v in items[:limit]]

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM vacancies
                WHERE posted_to_channel = 0
                ORDER BY fetched_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_vacancy(r) for r in rows]

    def get_by_track(
        self,
        track: str,
        junior_only: bool = False,
        remote_only: bool = False,
        limit: int = 5,
    ) -> List[Vacancy]:
        """Fetch latest vacancies filtered by track and optional badges."""
        if self._use_json:
            items = list(self._json_store.values())
            if track:
                items = [v for v in items if v.get("track") == track]
            if junior_only:
                items = [v for v in items if v.get("is_junior")]
            if remote_only:
                items = [v for v in items if v.get("is_remote")]
            items.sort(key=lambda x: x.get("fetched_at", ""), reverse=True)
            return [Vacancy(**v) for v in items[:limit]]

        clauses = ["1=1"]
        params: list = []
        if track:
            clauses.append("track = ?")
            params.append(track)
        if junior_only:
            clauses.append("is_junior = 1")
        if remote_only:
            clauses.append("is_remote = 1")
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM vacancies
                WHERE {' AND '.join(clauses)}
                ORDER BY fetched_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_row_to_vacancy(r) for r in rows]

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        """Return aggregate statistics."""
        if self._use_json:
            total = len(self._json_store)
            posted = sum(1 for v in self._json_store.values() if v.get("posted_to_channel"))
            by_track: Dict[str, int] = {}
            by_source: Dict[str, int] = {}
            for v in self._json_store.values():
                t = v.get("track", "unknown")
                by_track[t] = by_track.get(t, 0) + 1
                s = v.get("source", "unknown")
                by_source[s] = by_source.get(s, 0) + 1
            return {"total": total, "posted": posted, **by_track, **by_source}

        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
            posted = conn.execute(
                "SELECT COUNT(*) FROM vacancies WHERE posted_to_channel = 1"
            ).fetchone()[0]
            track_rows = conn.execute(
                "SELECT track, COUNT(*) as cnt FROM vacancies GROUP BY track"
            ).fetchall()
            source_rows = conn.execute(
                "SELECT source, COUNT(*) as cnt FROM vacancies GROUP BY source"
            ).fetchall()

        result: Dict[str, int] = {"total": total, "posted": posted}
        for row in track_rows:
            result[f"track_{row['track'] or 'unknown'}"] = row["cnt"]
        for row in source_rows:
            result[f"source_{row['source']}"] = row["cnt"]
        return result

    # ── Subscriber preferences ────────────────────────────────────────────────

    def set_subscriber_prefs(self, prefs: SubscriberPrefs) -> None:
        if self._use_json:
            return  # JSON fallback doesn't support subscriber store
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO subscribers (user_id, tracks, junior_only, remote_only)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    tracks = excluded.tracks,
                    junior_only = excluded.junior_only,
                    remote_only = excluded.remote_only
                """,
                (
                    prefs.user_id,
                    json.dumps(prefs.tracks),
                    int(prefs.junior_only),
                    int(prefs.remote_only),
                ),
            )

    def get_subscriber_prefs(self, user_id: int) -> Optional[SubscriberPrefs]:
        if self._use_json:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM subscribers WHERE user_id = ?", (user_id,)
            ).fetchone()
        if not row:
            return None
        return SubscriberPrefs(
            user_id=row["user_id"],
            tracks=json.loads(row["tracks"]),
            junior_only=bool(row["junior_only"]),
            remote_only=bool(row["remote_only"]),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_vacancy(row: sqlite3.Row) -> Vacancy:
    return Vacancy(
        source_id=row["source_id"],
        source=row["source"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        description=row["description"],
        url=row["url"],
        salary=row["salary"],
        track=row["track"],
        hashtags=row["hashtags"],
        is_junior=bool(row["is_junior"]),
        is_remote=bool(row["is_remote"]),
        contacts_json=row["contacts_json"],
        posted_to_channel=bool(row["posted_to_channel"]),
        fetched_at=row["fetched_at"],
    )


# ── Module-level singleton ────────────────────────────────────────────────────
db = Database()
