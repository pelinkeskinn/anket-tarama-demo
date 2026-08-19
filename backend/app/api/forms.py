from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.database import create_form, delete_form, get_form, list_form_details, list_forms
from app.db import get_session
from app.models import StoredFormCreate, StoredFormDetail, StoredFormSummary


router = APIRouter(prefix="/api/forms", tags=["forms"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Kayıt bulunamadı."}})


@router.post("", response_model=StoredFormDetail, status_code=201)
def save_form(payload: StoredFormCreate, session: Session = Depends(get_session)) -> StoredFormDetail:
    return create_form(payload, session)


@router.get("", response_model=list[StoredFormSummary])
def forms(session: Session = Depends(get_session)) -> list[StoredFormSummary]:
    return list_forms(session)


@router.get("/export.xlsx")
def export_forms(session: Session = Depends(get_session)) -> StreamingResponse:
    forms = list_form_details(session)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Anket Kayıtları"
    headers = ["Kayıt No", "Tarih", "Şablon", "Güven (%)", "Boş", "Manuel", *[f"Soru {number}" for number in range(1, 27)]]
    sheet.append(headers)

    header_fill = PatternFill("solid", fgColor="C1121F")
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for form in forms:
        answers = {answer.questionNo: _answer_label(form.templateCode, answer.questionNo, answer.value) for answer in form.answers}
        sheet.append(
            [
                form.id,
                form.createdAt.replace(tzinfo=None),
                form.templateCode,
                round(form.formConfidence * 100, 1),
                form.blankCount,
                form.manualCount,
                *[answers.get(number, "") for number in range(1, 27)],
            ]
        )

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.column_dimensions["A"].width = 12
    sheet.column_dimensions["B"].width = 21
    sheet.column_dimensions["C"].width = 25
    for column in range(4, 33):
        sheet.column_dimensions[get_column_letter(column)].width = 17

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="anket-kayitlari.xlsx"'}
    return StreamingResponse(output, headers=headers, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _answer_label(template_code: str, question_no: int, value: str | None) -> str:
    if value is None:
        return "Belirsiz"
    if value == "BLANK":
        return "Boş"
    if template_code.startswith("HEALTHY_NUTRITION_V"):
        if question_no >= 12:
            return {"NEVER": "Hiçbir zaman", "SOMETIMES": "1-2 kez/hafta", "OFTEN": "3-4 kez/hafta", "ALWAYS": "5+ kez/hafta"}.get(value, value)
        return {"NEVER": "Hiçbir zaman", "SOMETIMES": "Ara sıra", "OFTEN": "Sık sık", "ALWAYS": "Her zaman"}.get(value, value)
    return {"NEVER": "Hiçbir zaman", "SOMETIMES": "Bazen", "OFTEN": "Sık sık", "ALWAYS": "Her zaman"}.get(value, value)


@router.get("/{form_id}", response_model=StoredFormDetail)
def form_detail(form_id: int, session: Session = Depends(get_session)) -> StoredFormDetail:
    form = get_form(form_id, session)
    if form is None:
        raise _not_found()
    return form


@router.delete("/{form_id}")
def remove_form(form_id: int, session: Session = Depends(get_session)) -> dict[str, bool]:
    if not delete_form(form_id, session):
        raise _not_found()
    return {"deleted": True}
