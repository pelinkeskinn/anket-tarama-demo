from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import create_form, delete_form, get_form, iter_form_details, list_forms
from app.db import Base
from app.entities import AuditLog, FormAnswer, StoredForm
from app.models import AnswerResult, StoredFormCreate


def payload(analysis_id: str = "analysis-1", value: str = "SOMETIMES") -> StoredFormCreate:
    return StoredFormCreate(
        analysisId=analysis_id,
        templateCode="OMR_SURVEY_V2",
        formConfidence=0.97,
        answers=[
            AnswerResult(
                questionNo=question_no,
                value=value,  # type: ignore[arg-type]
                confidence=0.95,
                source="AUTO",
                status="OK",
            )
            for question_no in range(1, 26)
        ],
    )


def test_form_repository_lifecycle(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        created = create_form(payload(), session)
        repeated = create_form(payload(), session)

        assert repeated.id == created.id
        items, total = list_forms(session)
        assert total == 1
        assert len(items) == 1
        assert get_form(created.id, session) == created
        assert session.scalar(select(FormAnswer).where(FormAnswer.form_id == created.id).limit(1)) is not None
        assert session.scalar(select(AuditLog).where(AuditLog.action == "form.create")) is not None
        assert delete_form(created.id, session) is True
        assert delete_form(created.id, session) is False
        assert get_form(created.id, session) is None
        stored = session.get(StoredForm, created.id)
        assert stored is not None
        assert stored.deleted_at is not None
        items, total = list_forms(session)
        assert total == 0
        assert list(iter_form_details(session)) == []


def test_pagination_and_duplicate_flag(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        first = create_form(payload("a-1"), session)
        second = create_form(payload("a-2"), session)
        create_form(payload("a-3", value="ALWAYS"), session)

        assert first.possibleDuplicate is False
        assert second.possibleDuplicate is True
        page, total = list_forms(session, limit=2, offset=0)
        assert total == 3
        assert len(page) == 2
        page2, _ = list_forms(session, limit=2, offset=2)
        assert len(page2) == 1
