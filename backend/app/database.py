from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import DATABASE_PATH
from app.db import Base, SessionLocal, engine
from app.entities import StoredForm
from app.models import AnswerResult, StoredFormCreate, StoredFormDetail, StoredFormSummary


def init_db() -> None:
    # Alembic owns schema changes in production. This keeps local development and
    # existing deployments bootstrappable until the first managed migration runs.
    Base.metadata.create_all(bind=engine)


def create_form(payload: StoredFormCreate, session: Session | None = None) -> StoredFormDetail:
    owns_session = session is None
    db = session or SessionLocal()
    try:
        existing = db.scalar(select(StoredForm).where(StoredForm.analysis_id == payload.analysisId))
        if existing is not None:
            return _to_detail(existing)
        entity = StoredForm(
            analysis_id=payload.analysisId,
            template_code=payload.templateCode,
            created_at=datetime.now(timezone.utc),
            form_confidence=payload.formConfidence,
            blank_count=sum(1 for answer in payload.answers if answer.value == "BLANK" or answer.status == "BLANK"),
            manual_count=sum(1 for answer in payload.answers if answer.source == "MANUAL"),
            answers=[answer.model_dump() for answer in payload.answers],
        )
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return _to_detail(entity)
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(StoredForm).where(StoredForm.analysis_id == payload.analysisId))
        if existing is None:
            raise
        return _to_detail(existing)
    finally:
        if owns_session:
            db.close()


def list_forms(session: Session | None = None) -> list[StoredFormSummary]:
    owns_session = session is None
    db = session or SessionLocal()
    try:
        rows = db.scalars(select(StoredForm).order_by(StoredForm.id.desc())).all()
        return [_to_summary(row) for row in rows]
    finally:
        if owns_session:
            db.close()


def list_form_details(session: Session | None = None) -> list[StoredFormDetail]:
    owns_session = session is None
    db = session or SessionLocal()
    try:
        rows = db.scalars(select(StoredForm).order_by(StoredForm.id.asc())).all()
        return [_to_detail(row) for row in rows]
    finally:
        if owns_session:
            db.close()


def get_form(form_id: int, session: Session | None = None) -> StoredFormDetail | None:
    owns_session = session is None
    db = session or SessionLocal()
    try:
        row = db.get(StoredForm, form_id)
        return _to_detail(row) if row else None
    finally:
        if owns_session:
            db.close()


def delete_form(form_id: int, session: Session | None = None) -> bool:
    owns_session = session is None
    db = session or SessionLocal()
    try:
        result = db.execute(delete(StoredForm).where(StoredForm.id == form_id))
        db.commit()
        return bool(result.rowcount)
    finally:
        if owns_session:
            db.close()


def _to_summary(row: StoredForm) -> StoredFormSummary:
    return StoredFormSummary(
        id=row.id,
        createdAt=row.created_at,
        formConfidence=row.form_confidence,
        blankCount=row.blank_count,
        manualCount=row.manual_count,
    )


def _to_detail(row: StoredForm) -> StoredFormDetail:
    return StoredFormDetail(
        **_to_summary(row).model_dump(),
        analysisId=row.analysis_id,
        templateCode=row.template_code,
        answers=[AnswerResult(**answer) for answer in row.answers],
    )


def temporary_image_files() -> list[Path]:
    data_dir = DATABASE_PATH.parent
    if not data_dir.exists():
        return []
    return [path for path in data_dir.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
