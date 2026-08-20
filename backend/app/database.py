from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import DATABASE_PATH
from app.db import Base, SessionLocal, engine
from app.entities import AuditLog, FormAnswer, StoredForm
from app.models import AnswerResult, StoredFormCreate, StoredFormDetail, StoredFormSummary
from app.scoring import answer_score

logger = logging.getLogger("anket_tarama")

DUPLICATE_WINDOW = timedelta(minutes=5)
EXPORT_BATCH_SIZE = 500
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


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
            if existing.deleted_at is not None:
                existing.deleted_at = None
                db.commit()
                db.refresh(existing)
            return _to_detail(existing)
        now = datetime.now(timezone.utc)
        possible_duplicate = _has_recent_duplicate(db, payload, now)
        entity = StoredForm(
            analysis_id=payload.analysisId,
            template_code=payload.templateCode,
            created_at=now,
            form_confidence=payload.formConfidence,
            blank_count=sum(1 for answer in payload.answers if answer.value == "BLANK" or answer.status == "BLANK"),
            manual_count=sum(1 for answer in payload.answers if answer.source == "MANUAL"),
            answers=[answer.model_dump() for answer in payload.answers],
            possible_duplicate=possible_duplicate,
        )
        db.add(entity)
        db.flush()
        _replace_normalized_answers(db, entity.id, payload.answers)
        _write_audit(db, "form.create", entity.id, entity.analysis_id, {"templateCode": entity.template_code})
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


def list_forms(
    session: Session | None = None,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> tuple[list[StoredFormSummary], int]:
    owns_session = session is None
    db = session or SessionLocal()
    try:
        limit = min(max(int(limit), 1), MAX_PAGE_SIZE)
        offset = max(int(offset), 0)
        active = StoredForm.deleted_at.is_(None)
        total = int(db.scalar(select(func.count()).select_from(StoredForm).where(active)) or 0)
        rows = db.scalars(
            select(StoredForm).where(active).order_by(StoredForm.id.desc()).offset(offset).limit(limit)
        ).all()
        return [_to_summary(row) for row in rows], total
    finally:
        if owns_session:
            db.close()


def list_form_details(session: Session | None = None) -> list[StoredFormDetail]:
    return list(iter_form_details(session))


def iter_form_details(session: Session | None = None, batch_size: int = EXPORT_BATCH_SIZE) -> Iterator[StoredFormDetail]:
    owns_session = session is None
    db = session or SessionLocal()
    try:
        last_id = 0
        while True:
            rows = db.scalars(
                select(StoredForm)
                .where(StoredForm.deleted_at.is_(None), StoredForm.id > last_id)
                .order_by(StoredForm.id.asc())
                .limit(max(int(batch_size), 1))
            ).all()
            if not rows:
                break
            for row in rows:
                yield _to_detail(row)
                last_id = row.id
    finally:
        if owns_session:
            db.close()


def get_form(form_id: int, session: Session | None = None) -> StoredFormDetail | None:
    owns_session = session is None
    db = session or SessionLocal()
    try:
        row = db.get(StoredForm, form_id)
        if row is None or row.deleted_at is not None:
            return None
        return _to_detail(row)
    finally:
        if owns_session:
            db.close()


def delete_form(form_id: int, session: Session | None = None) -> bool:
    owns_session = session is None
    db = session or SessionLocal()
    try:
        row = db.get(StoredForm, form_id)
        if row is None or row.deleted_at is not None:
            return False
        row.deleted_at = datetime.now(timezone.utc)
        _write_audit(db, "form.delete", row.id, row.analysis_id, None)
        db.commit()
        return True
    finally:
        if owns_session:
            db.close()


def _has_recent_duplicate(db: Session, payload: StoredFormCreate, now: datetime) -> bool:
    signature = _answer_signature(payload.answers)
    window_start = now - DUPLICATE_WINDOW
    recent = db.scalars(
        select(StoredForm).where(StoredForm.deleted_at.is_(None), StoredForm.created_at >= window_start)
    ).all()
    return any(_answer_signature_from_json(row.answers) == signature for row in recent)


def _answer_signature(answers: list[AnswerResult]) -> str:
    return "|".join(f"{answer.questionNo}:{(answer.value or '')}" for answer in sorted(answers, key=lambda item: item.questionNo))


def _answer_signature_from_json(answers: list[dict[str, object]]) -> str:
    items = sorted(answers, key=lambda item: int(item.get("questionNo") or 0))
    return "|".join(f"{item.get('questionNo')}:{(item.get('value') or '')}" for item in items)


def _replace_normalized_answers(db: Session, form_id: int, answers: list[AnswerResult]) -> None:
    existing = db.scalars(select(FormAnswer).where(FormAnswer.form_id == form_id)).all()
    for row in existing:
        db.delete(row)
    for answer in answers:
        db.add(
            FormAnswer(
                form_id=form_id,
                question_no=answer.questionNo,
                value=answer.value,
                score=answer_score(answer.value, answer.status),
                status=answer.status,
                source=answer.source,
            )
        )


def _write_audit(db: Session, action: str, form_id: int | None, analysis_id: str | None, details: dict[str, object] | None) -> None:
    db.add(
        AuditLog(
            created_at=datetime.now(timezone.utc),
            action=action,
            form_id=form_id,
            analysis_id=analysis_id,
            details=details,
        )
    )
    logger.info(
        json.dumps(
            {
                "event": action,
                "formId": form_id,
                "analysisId": analysis_id,
                "details": details,
            },
            ensure_ascii=False,
        )
    )


def _to_summary(row: StoredForm) -> StoredFormSummary:
    return StoredFormSummary(
        id=row.id,
        createdAt=row.created_at,
        formConfidence=row.form_confidence,
        blankCount=row.blank_count,
        manualCount=row.manual_count,
        possibleDuplicate=bool(row.possible_duplicate),
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
