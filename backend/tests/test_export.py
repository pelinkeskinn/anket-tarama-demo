from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, get_session
from app.main import app
from app.models import AnswerResult, StoredFormCreate
from app.database import create_form
from app.scoring import SCORE_MAP


def _override_db(tmp_path):  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite:///{(tmp_path / 'export.db').as_posix()}")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override() -> Session:  # type: ignore[misc]
        with TestingSession() as session:
            yield session

    app.dependency_overrides[get_session] = override
    return TestingSession


def _answers() -> list[AnswerResult]:
    values = ["NEVER", "SOMETIMES", "OFTEN", "ALWAYS", "BLANK"]
    statuses = ["OK", "OK", "OK", "OK", "BLANK"]
    answers = []
    for question_no in range(1, 26):
        if question_no == 6:
            answers.append(
                AnswerResult(questionNo=6, value=None, confidence=0.4, source="UNRESOLVED", status="UNCERTAIN")
            )
            continue
        index = (question_no - 1) % 5
        answers.append(
            AnswerResult(
                questionNo=question_no,
                value=values[index],  # type: ignore[arg-type]
                confidence=0.9,
                source="AUTO",
                status=statuses[index],  # type: ignore[arg-type]
            )
        )
    return answers


def test_numeric_export_scores_and_summary(tmp_path) -> None:  # type: ignore[no-untyped-def]
    TestingSession = _override_db(tmp_path)
    with TestingSession() as session:
        create_form(
            StoredFormCreate(
                analysisId="export-1",
                templateCode="OMR_SURVEY_V2",
                formConfidence=0.9,
                answers=_answers(),
            ),
            session,
        )

    client = TestClient(app)
    try:
        response = client.get("/api/forms/export.xlsx?format=numeric")
        assert response.status_code == 200
        workbook = load_workbook(BytesIO(response.content))
        sheet = workbook["Anket Kayıtları"]
        summary = workbook["Özet"]
        assert sheet["G2"].value == SCORE_MAP["NEVER"]
        assert sheet["H2"].value == SCORE_MAP["SOMETIMES"]
        assert sheet["I2"].value == SCORE_MAP["OFTEN"]
        assert sheet["J2"].value == SCORE_MAP["ALWAYS"]
        assert sheet["K2"].value is None
        assert sheet["L2"].value is None
        fill = str(sheet["L2"].fill.fgColor.rgb or sheet["L2"].fill.fgColor.theme)
        assert "F4A261" in fill.upper() or sheet["L2"].fill.patternType == "solid"
        assert sheet.cell(1, 33).value == "Toplam Puan"
        assert sheet.cell(1, 34).value == "Yanıtlanan Soru Sayısı"
        assert isinstance(sheet.cell(2, 33).value, (int, float))
        assert summary["B2"].value == 1
        text_response = client.get("/api/forms/export.xlsx?format=text")
        text_book = load_workbook(BytesIO(text_response.content))
        assert text_book.active["G2"].value == "Hiçbir zaman"
    finally:
        app.dependency_overrides.clear()


def test_forms_list_is_paginated(tmp_path) -> None:  # type: ignore[no-untyped-def]
    TestingSession = _override_db(tmp_path)
    with TestingSession() as session:
        for index in range(3):
            create_form(
                StoredFormCreate(
                    analysisId=f"page-{index}",
                    templateCode="OMR_SURVEY_V2",
                    formConfidence=0.9,
                    answers=_answers(),
                ),
                session,
            )
    client = TestClient(app)
    try:
        response = client.get("/api/forms?limit=2&offset=0")
        payload = response.json()
        assert response.status_code == 200
        assert payload["total"] == 3
        assert len(payload["items"]) == 2
        assert "possibleDuplicate" in payload["items"][0]
    finally:
        app.dependency_overrides.clear()


def test_admin_token_protects_form_reads(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    _override_db(tmp_path)
    client = TestClient(app)
    try:
        denied = client.get("/api/forms")
        assert denied.status_code == 401
        allowed = client.get("/api/forms", headers={"X-Admin-Token": "test-admin"})
        assert allowed.status_code == 200
        assert allowed.json() == {"items": [], "total": 0}
        export_denied = client.get("/api/forms/export.xlsx")
        assert export_denied.status_code == 401
    finally:
        app.dependency_overrides.clear()
