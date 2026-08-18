from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import create_form, delete_form, get_form, list_forms
from app.db import Base
from app.models import AnswerResult, StoredFormCreate


def payload(analysis_id: str = "analysis-1") -> StoredFormCreate:
    return StoredFormCreate(
        analysisId=analysis_id,
        templateCode="OMR_SURVEY_V2",
        formConfidence=0.97,
        answers=[
            AnswerResult(
                questionNo=question_no,
                value="SOMETIMES",
                confidence=0.95,
                source="AUTO",
                status="OK",
            )
            for question_no in range(1, 26)
        ],
    )


def test_form_repository_lifecycle(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        created = create_form(payload(), session)
        repeated = create_form(payload(), session)

        assert repeated.id == created.id
        assert len(list_forms(session)) == 1
        assert get_form(created.id, session) == created
        assert delete_form(created.id, session) is True
        assert delete_form(created.id, session) is False
        assert get_form(created.id, session) is None
