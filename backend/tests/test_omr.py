from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import SAMPLE_FORMS_DIR
from app.database import temporary_image_files
from app.errors import OmrError
from app.omr import analyze_image_bytes


ROOT = Path(__file__).resolve().parents[2]


def image_bytes(name: str) -> bytes:
    return (SAMPLE_FORMS_DIR / name).read_bytes()


def answer_map(response) -> dict[int, str | None]:
    return {answer.questionNo: answer.status if answer.status != "OK" else answer.value for answer in response.answers}


def test_clean_form_is_read_correctly() -> None:
    expected = json.loads((ROOT / "sample-forms" / "expected-results.json").read_text(encoding="utf-8"))["filled-clean.png"]
    response = analyze_image_bytes(image_bytes("filled-clean.png"))
    values = {str(answer.questionNo): answer.value for answer in response.answers}
    assert values == expected
    assert response.status == "OK"


def test_blank_answers_return_blank() -> None:
    response = analyze_image_bytes(image_bytes("filled-with-blanks.png"))
    answers = {answer.questionNo: answer for answer in response.answers}
    assert answers[4].status == "BLANK"
    assert answers[19].value == "BLANK"
    assert response.blankCount == 2


def test_double_mark_returns_double_mark() -> None:
    response = analyze_image_bytes(image_bytes("filled-double-mark.png"))
    answer = {answer.questionNo: answer for answer in response.answers}[7]
    assert answer.status == "DOUBLE_MARK"
    assert answer.source == "UNRESOLVED"


def test_low_confidence_answer_returns_uncertain() -> None:
    response = analyze_image_bytes(image_bytes("filled-faint-marks.png"))
    answer = {answer.questionNo: answer for answer in response.answers}[5]
    assert answer.status == "UNCERTAIN"
    assert answer.confidence < 0.7


def test_missing_markers_returns_error() -> None:
    with pytest.raises(OmrError) as exc:
        analyze_image_bytes(image_bytes("blank-form.png").replace(b"\x00", b"\xff", 1000))
    assert exc.value.code in {"MARKERS_NOT_FOUND", "INVALID_FILE"}


def test_non_image_file_is_rejected() -> None:
    with pytest.raises(OmrError) as exc:
        analyze_image_bytes(b"not an image")
    assert exc.value.code == "INVALID_FILE"


def test_large_file_is_rejected() -> None:
    with pytest.raises(OmrError) as exc:
        analyze_image_bytes(b"0" * 13_000_000)
    assert exc.value.code == "INVALID_FILE"


def test_no_temporary_image_remains_after_processing() -> None:
    before = set(temporary_image_files())
    analyze_image_bytes(image_bytes("filled-clean.png"))
    after = set(temporary_image_files())
    assert after == before


def test_all_25_questions_are_returned() -> None:
    response = analyze_image_bytes(image_bytes("filled-clean.png"))
    assert len(response.answers) == 25
    assert [answer.questionNo for answer in response.answers] == list(range(1, 26))


def test_form_confidence_is_generated() -> None:
    response = analyze_image_bytes(image_bytes("filled-clean.png"))
    assert 0 < response.formConfidence <= 1

