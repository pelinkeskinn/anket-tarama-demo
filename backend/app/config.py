from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = ROOT_DIR / "backend" / "templates" / "demo_form_v1.json"
HEALTHY_NUTRITION_TEMPLATE_PATH = ROOT_DIR / "backend" / "templates" / "healthy_nutrition_survey_v1.json"
HEALTHY_NUTRITION_TEMPLATE_V2_PATH = ROOT_DIR / "backend" / "templates" / "healthy_nutrition_survey_v2.json"
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", ROOT_DIR / "backend" / "data" / "demo.db"))
SAMPLE_FORMS_DIR = ROOT_DIR / "sample-forms"
OMR_DEBUG_DIR = Path(os.getenv("OMR_DEBUG_DIR", ROOT_DIR / "backend" / "debug"))
OMR_DEBUG_ENABLED = os.getenv("OMR_DEBUG_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "12000000"))
MAX_MANUAL_REVIEW_QUESTIONS = int(os.getenv("MAX_MANUAL_REVIEW_QUESTIONS", "4"))

EMPTY_THRESHOLD = float(os.getenv("OMR_EMPTY_THRESHOLD", "0.23"))
MARK_THRESHOLD = float(os.getenv("OMR_MARK_THRESHOLD", "0.25"))
UNCERTAIN_MARGIN = float(os.getenv("OMR_UNCERTAIN_MARGIN", "0.07"))
DOUBLE_MARK_THRESHOLD = float(os.getenv("OMR_DOUBLE_MARK_THRESHOLD", "0.34"))


def _default_database_url() -> str:
    return f"sqlite:///{DATABASE_PATH.as_posix()}"


def _csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, default).split(",") if value.strip())


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", _default_database_url())
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    database_url: str
    cors_origins: tuple[str, ...]
    cors_origin_regex: str | None


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Anket Tarama API"),
        environment=os.getenv("APP_ENV", "development"),
        database_url=_database_url(),
        cors_origins=_csv_env("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"),
        cors_origin_regex=os.getenv(
            "CORS_ORIGIN_REGEX",
            r"https?://([A-Za-z0-9-]+\.onrender\.com|[A-Za-z0-9-]+\.vercel\.app)(:\d+)?$",
        )
        or None,
    )

