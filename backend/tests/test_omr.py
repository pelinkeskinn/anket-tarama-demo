from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import cv2
import pytest
from PIL import Image

from app.config import SAMPLE_FORMS_DIR
from app.database import temporary_image_files
from app.errors import OmrError
from app.omr import analyze_image_bytes


ROOT = Path(__file__).resolve().parents[2]


def image_bytes(name: str) -> bytes:
    return (SAMPLE_FORMS_DIR / name).read_bytes()


def resized_image_bytes(name: str, width: int) -> bytes:
    image = cv2.imread(str(SAMPLE_FORMS_DIR / name))
    height = int(image.shape[0] * width / image.shape[1])
    resized = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    success, encoded = cv2.imencode(".png", resized)
    assert success
    return encoded.tobytes()


def markerless_image_bytes(name: str) -> bytes:
    image = cv2.imread(str(SAMPLE_FORMS_DIR / name))
    margin = 140
    size = 130
    height, width = image.shape[:2]
    for x, y in [
        (margin, margin),
        (width - margin - size, margin),
        (width - margin - size, height - margin - size),
        (margin, height - margin - size),
    ]:
        image[y : y + size, x : x + size] = 255
    success, encoded = cv2.imencode(".png", image)
    assert success
    return encoded.tobytes()


def exif_rotated_jpeg_bytes(name: str) -> bytes:
    with Image.open(SAMPLE_FORMS_DIR / name) as image:
        rotated_pixels = image.rotate(90, expand=True)
        exif = Image.Exif()
        exif[274] = 6
        output = BytesIO()
        rotated_pixels.save(output, format="JPEG", quality=90, exif=exif)
        return output.getvalue()


def pixel_rotated_jpeg_bytes(name: str) -> bytes:
    image = cv2.imread(str(SAMPLE_FORMS_DIR / name))
    rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    success, encoded = cv2.imencode(".jpg", rotated, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    assert success
    return encoded.tobytes()


def answer_map(response) -> dict[int, str | None]:
    return {answer.questionNo: answer.status if answer.status != "OK" else answer.value for answer in response.answers}


def test_clean_form_is_read_correctly() -> None:
    expected = json.loads((ROOT / "sample-forms" / "expected-results.json").read_text(encoding="utf-8"))["filled-clean.png"]
    response = analyze_image_bytes(image_bytes("filled-clean.png"))
    values = {str(answer.questionNo): answer.value for answer in response.answers}
    assert values == expected
    assert response.status == "OK"


def test_low_resolution_manual_upload_is_read_correctly() -> None:
    response = analyze_image_bytes(resized_image_bytes("filled-clean.png", 500))
    assert response.status == "OK"
    assert len(response.answers) == 25


def test_full_page_upload_falls_back_when_markers_are_missing() -> None:
    response = analyze_image_bytes(markerless_image_bytes("filled-clean.png"))
    assert response.status == "OK"
    assert len(response.answers) == 25


def test_uploaded_kizilay_forms_are_accepted() -> None:
    for filename in ["IMG_4134(1).png", "IMG_4135.png", "IMG_4136.png", "IMG_4137.png"]:
        response = analyze_image_bytes(image_bytes(filename))
        assert response.templateCode == "KR_SURVEY_V1"
        assert response.status != "TOO_MANY_UNCERTAIN"
        assert response.reviewRequiredCount <= 4


def test_jpeg_exif_orientation_is_applied() -> None:
    response = analyze_image_bytes(exif_rotated_jpeg_bytes("IMG_4137.png"))
    assert response.templateCode == "KR_SURVEY_V1"
    assert response.status != "TOO_MANY_UNCERTAIN"


def test_pixel_rotated_jpeg_is_accepted() -> None:
    response = analyze_image_bytes(pixel_rotated_jpeg_bytes("IMG_4137.png"))
    assert response.templateCode == "KR_SURVEY_V1"
    assert response.status != "TOO_MANY_UNCERTAIN"


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

