from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import DATABASE_PATH
from app.models import AnswerResult, StoredFormCreate, StoredFormDetail, StoredFormSummary


def _connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS demo_forms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id TEXT NOT NULL,
                template_code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                form_confidence REAL NOT NULL,
                blank_count INTEGER NOT NULL,
                manual_count INTEGER NOT NULL,
                answers_json TEXT NOT NULL
            )
            """
        )


def create_form(payload: StoredFormCreate) -> StoredFormDetail:
    answers_json = json.dumps([answer.model_dump() for answer in payload.answers], ensure_ascii=False)
    blank_count = sum(1 for answer in payload.answers if answer.value == "BLANK" or answer.status == "BLANK")
    manual_count = sum(1 for answer in payload.answers if answer.source == "MANUAL")
    created_at = datetime.now(timezone.utc).isoformat()

    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO demo_forms
                (analysis_id, template_code, created_at, form_confidence, blank_count, manual_count, answers_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.analysisId,
                payload.templateCode,
                created_at,
                payload.formConfidence,
                blank_count,
                manual_count,
                answers_json,
            ),
        )
        form_id = int(cursor.lastrowid)

    detail = get_form(form_id)
    if detail is None:
        raise RuntimeError("Saved form could not be read back")
    return detail


def list_forms() -> list[StoredFormSummary]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, created_at, form_confidence, blank_count, manual_count
            FROM demo_forms
            ORDER BY id DESC
            """
        ).fetchall()
    return [
        StoredFormSummary(
            id=int(row["id"]),
            createdAt=datetime.fromisoformat(row["created_at"]),
            formConfidence=float(row["form_confidence"]),
            blankCount=int(row["blank_count"]),
            manualCount=int(row["manual_count"]),
        )
        for row in rows
    ]


def get_form(form_id: int) -> StoredFormDetail | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM demo_forms WHERE id = ?", (form_id,)).fetchone()
    if row is None:
        return None

    answers = [AnswerResult(**answer) for answer in json.loads(str(row["answers_json"]))]
    return StoredFormDetail(
        id=int(row["id"]),
        createdAt=datetime.fromisoformat(row["created_at"]),
        analysisId=str(row["analysis_id"]),
        templateCode=str(row["template_code"]),
        formConfidence=float(row["form_confidence"]),
        blankCount=int(row["blank_count"]),
        manualCount=int(row["manual_count"]),
        answers=answers,
    )


def delete_form(form_id: int) -> bool:
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM demo_forms WHERE id = ?", (form_id,))
        return cursor.rowcount > 0


def temporary_image_files() -> list[Path]:
    data_dir = DATABASE_PATH.parent
    if not data_dir.exists():
        return []
    return [path for path in data_dir.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]

