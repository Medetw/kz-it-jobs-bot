"""Central configuration: env settings, track keyword maps, channel lists."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Set

from dotenv import load_dotenv

load_dotenv()

# ── Bot credentials ───────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
TARGET_CHANNEL: str = os.getenv("TARGET_CHANNEL", "")          # e.g. @my_jobs_channel
PROXY_URL: str = os.getenv("PROXY_URL", "")                    # socks5://user:pass@host:port  or  http://host:port
ADMIN_IDS: List[int] = [
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]

# ── Scheduler ─────────────────────────────────────────────────────────────────
POLL_INTERVAL_MINUTES: int = int(os.getenv("POLL_INTERVAL_MINUTES", "30"))
POST_DELAY_SECONDS: float = float(os.getenv("POST_DELAY_SECONDS", "2.5"))

# ── Storage ───────────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "jobs.db")
JSON_FALLBACK_PATH: str = os.getenv("JSON_FALLBACK_PATH", "jobs_fallback.json")

# ── HH.kz API ─────────────────────────────────────────────────────────────────
HH_BASE_URL: str = "https://api.hh.ru"
HH_AREA_KAZAKHSTAN: int = 40     # Kazakhstan
HH_AREA_ALMATY: int = 160
HH_AREA_ASTANA: int = 159
HH_PER_PAGE: int = 50
HH_REQUEST_DELAY: float = 0.4   # seconds between API calls

# ── Habr Career ───────────────────────────────────────────────────────────────
HABR_RSS_URL: str = (
    "https://career.habr.com/vacancies/rss"
    "?q=&type=all&country_id=64&currency=KZT"   # country_id 64 = Kazakhstan
)
HABR_REQUEST_DELAY: float = 1.0

# ── Telegram channel scraping ─────────────────────────────────────────────────
TELEGRAM_CHANNELS: List[str] = [
    "devkz_jobs",
    "astanahub_jobs",
    "kolesa_team",
    "it_jobs_kz",
]
TELEGRAM_PREVIEW_BASE: str = "https://t.me/s/"
TELEGRAM_REQUEST_DELAY: float = 1.5

# ── IT Track definitions ──────────────────────────────────────────────────────
@dataclass
class Track:
    name: str                           # canonical name
    hashtag: str                        # e.g. #backend
    emoji: str
    keywords: Set[str] = field(default_factory=set)
    tech_tags: List[str] = field(default_factory=list)  # extra hashtags


TRACKS: Dict[str, Track] = {
    "backend": Track(
        name="Backend",
        hashtag="#backend",
        emoji="⚙️",
        keywords={
            "backend", "back-end", "back end",
            "python", "django", "fastapi", "flask",
            "java", "spring", "spring boot",
            "golang", "go ", " go,",
            "c#", ".net", "dotnet", "asp.net",
            "node.js", "nodejs", "node js", "express",
            "php", "laravel", "symfony",
            "ruby", "rails",
            "rust", "scala", "kotlin server",
            "api", "rest api", "grpc", "microservices",
            "postgresql", "mysql", "mongodb", "redis",
            "серверный", "бэкенд",
        },
        tech_tags=["#python", "#java", "#golang", "#nodejs", "#php", "#dotnet"],
    ),
    "frontend": Track(
        name="Frontend",
        hashtag="#frontend",
        emoji="🖥️",
        keywords={
            "frontend", "front-end", "front end",
            "react", "react.js", "reactjs",
            "vue", "vue.js", "vuejs", "nuxt",
            "angular", "angularjs",
            "typescript", "javascript", "js developer",
            "html", "css", "scss", "sass",
            "webpack", "vite", "next.js", "nextjs",
            "svelte", "jquery",
            "фронтенд", "фронт",
        },
        tech_tags=["#react", "#vue", "#angular", "#typescript", "#javascript"],
    ),
    "qa": Track(
        name="QA",
        hashtag="#qa",
        emoji="🔍",
        keywords={
            "qa", "quality assurance", "тестировщик", "тестирование",
            "manual qa", "manual testing", "ручное тестирование",
            "automation qa", "автоматизация тестирования",
            "selenium", "playwright", "cypress", "appium",
            "pytest", "junit", "testng",
            "postman", "soapui",
            "test engineer", "sdet",
            "qa engineer", "qa analyst",
        },
        tech_tags=["#qa", "#testing", "#automation"],
    ),
    "mobile": Track(
        name="Mobile",
        hashtag="#mobile",
        emoji="📱",
        keywords={
            "mobile", "ios", "android",
            "swift", "swiftui", "objective-c",
            "kotlin", "kotlin android",
            "flutter", "dart",
            "react native", "reactnative",
            "xamarin", "ionic",
            "мобильный разработчик", "мобильная разработка",
        },
        tech_tags=["#ios", "#android", "#flutter", "#reactnative"],
    ),
    "data_devops": Track(
        name="Data/DevOps",
        hashtag="#data",
        emoji="📊",
        keywords={
            "data analyst", "data analysis", "аналитик данных",
            "data science", "data scientist", "машинное обучение",
            "machine learning", "ml engineer", "ai engineer",
            "bi analyst", "power bi", "tableau", "qlik",
            "devops", "dev ops", "site reliability",
            "docker", "kubernetes", "k8s", "helm",
            "linux", "bash", "ansible", "terraform", "jenkins",
            "ci/cd", "gitlab ci", "github actions",
            "cloud", "aws", "gcp", "azure",
            "spark", "hadoop", "airflow", "dbt", "kafka",
            "etl", "data pipeline", "data warehouse",
        },
        tech_tags=["#devops", "#datascience", "#docker", "#kubernetes", "#linux"],
    ),
}

# ── HH search queries per track ───────────────────────────────────────────────
HH_SEARCH_QUERIES: Dict[str, List[str]] = {
    "backend": [
        "Python developer", "Java developer", "Backend developer",
        "Golang developer", ".NET developer", "PHP developer",
    ],
    "frontend": [
        "Frontend developer", "React developer", "Vue developer",
        "JavaScript developer", "Angular developer",
    ],
    "qa": [
        "QA engineer", "Software tester", "Automation QA",
        "Manual tester", "QA analyst",
    ],
    "mobile": [
        "iOS developer", "Android developer", "Flutter developer",
        "React Native developer", "Mobile developer",
    ],
    "data_devops": [
        "Data analyst", "Data scientist", "DevOps engineer",
        "Machine learning engineer", "BI analyst",
        "Data engineer", "MLOps", "SRE",
    ],
}

# ── Experience filters for junior/internship priority ─────────────────────────
HH_EXPERIENCE_FILTERS: List[str] = ["noExperience", "between1And3"]

# ── City / format detection ───────────────────────────────────────────────────
CITY_KEYWORDS: Dict[str, str] = {
    "алматы": "#almaty",
    "almaty": "#almaty",
    "алма-ата": "#almaty",
    "астана": "#astana",
    "astana": "#astana",
    "нур-султан": "#astana",
    "нурсултан": "#astana",
    "шымкент": "#shymkent",
    "shymkent": "#shymkent",
    "қарағанды": "#karaganda",
    "караганда": "#karaganda",
    "karaganda": "#karaganda",
}

REMOTE_KEYWORDS: Set[str] = {
    "удаленно", "удалённо", "remote", "дистанционно",
    "из любой точки", "anywhere",
}

JUNIOR_KEYWORDS: Set[str] = {
    "junior", "стажировка", "intern", "internship",
    "джуниор", "джун", "начинающий", "без опыта",
    "стажер", "стажёр",
}
