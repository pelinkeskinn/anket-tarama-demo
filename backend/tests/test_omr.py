from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.config import SAMPLE_FORMS_DIR
from app.database import temporary_image_files
from app.errors import OmrError
from app.omr import _find_warp_source, analyze_image_bytes


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


def child_marked_image_bytes(style: str) -> bytes:
    template = json.loads((ROOT / "backend" / "templates" / "demo_form_v1.json").read_text(encoding="utf-8"))
    expected = json.loads((ROOT / "sample-forms" / "expected-results.json").read_text(encoding="utf-8"))["filled-clean.png"]
    with Image.open(SAMPLE_FORMS_DIR / "blank-form.png") as image:
        marked = image.convert("RGB")
    draw = ImageDraw.Draw(marked)
    for question in template["questions"]:
        question_no = int(question["questionNo"])
        option = expected[str(question_no)]
        box = question["options"][option]
        center_x = int(box["x"]) + int(box["width"]) // 2
        center_y = int(box["y"]) + int(box["height"]) // 2
        if style == "tick":
            draw.line((center_x - 28, center_y + 2, center_x - 8, center_y + 24, center_x + 31, center_y - 28), fill="black", width=10)
        elif style == "x":
            draw.line((center_x - 30, center_y - 30, center_x + 30, center_y + 30), fill="black", width=9)
            draw.line((center_x + 30, center_y - 30, center_x - 30, center_y + 30), fill="black", width=9)
        elif style == "partial":
            draw.arc((center_x - 34, center_y - 34, center_x + 34, center_y + 34), start=205, end=515, fill="black", width=14)
            draw.line((center_x - 22, center_y + 15, center_x + 22, center_y - 15), fill="black", width=9)
        else:
            raise ValueError(style)
    output = BytesIO()
    marked.save(output, format="PNG")
    return output.getvalue()


def answer_map(response) -> dict[int, str | None]:
    return {answer.questionNo: answer.status if answer.status != "OK" else answer.value for answer in response.answers}


def test_clean_form_is_read_correctly() -> None:
    expected = json.loads((ROOT / "sample-forms" / "expected-results.json").read_text(encoding="utf-8"))["filled-clean.png"]
    response = analyze_image_bytes(image_bytes("filled-clean.png"))
    values = {str(answer.questionNo): answer.value for answer in response.answers}
    assert values == expected
    assert response.status == "OK"


def test_v2_aruco_form_is_read_correctly() -> None:
    expected = json.loads((ROOT / "sample-forms" / "expected-results.json").read_text(encoding="utf-8"))["filled-clean.png"]
    response = analyze_image_bytes(image_bytes("filled-clean-v2.png"))
    values = {str(answer.questionNo): answer.value for answer in response.answers}
    assert response.templateCode == "OMR_SURVEY_V2"
    assert response.status == "OK"
    assert values == expected


def test_v2_faint_marks_are_read_correctly() -> None:
    response = analyze_image_bytes(image_bytes("filled-faint-v2.png"))
    values = {answer.questionNo: answer.value for answer in response.answers}
    assert response.templateCode == "OMR_SURVEY_V2"
    assert response.status == "OK"
    assert values[5] == "SOMETIMES"
    assert values[14] == "SOMETIMES"


def test_low_resolution_manual_upload_is_read_correctly() -> None:
    response = analyze_image_bytes(resized_image_bytes("filled-clean.png", 500))
    assert response.status == "OK"
    assert len(response.answers) == 25


def test_full_page_upload_falls_back_when_markers_are_missing() -> None:
    response = analyze_image_bytes(markerless_image_bytes("filled-clean.png"))
    assert response.status == "OK"
    assert len(response.answers) == 25


def test_uploaded_kizilay_forms_are_accepted() -> None:
    for filename in ["IMG_4134(1).png", "IMG_4135.png", "IMG_4136.png", "IMG_4137.png", "IMG_4140.png", "IMG_4140.jpeg"]:
        response = analyze_image_bytes(image_bytes(filename))
        assert response.templateCode == "KR_SURVEY_V1"
        assert response.status != "TOO_MANY_UNCERTAIN"
        assert response.reviewRequiredCount <= 4


def test_faint_pencil_upload_is_read_correctly() -> None:
    response = analyze_image_bytes(image_bytes("IMG_4140.jpeg"))
    values = {answer.questionNo: answer.value for answer in response.answers}
    assert response.templateCode == "KR_SURVEY_V1"
    assert response.status == "OK"
    assert values == {
        1: "NEVER",
        2: "ALWAYS",
        3: "ALWAYS",
        4: "ALWAYS",
        5: "ALWAYS",
        6: "ALWAYS",
        7: "ALWAYS",
        8: "SOMETIMES",
        9: "SOMETIMES",
        10: "SOMETIMES",
        11: "ALWAYS",
        12: "ALWAYS",
        13: "ALWAYS",
        14: "SOMETIMES",
        15: "SOMETIMES",
        16: "SOMETIMES",
        17: "ALWAYS",
        18: "ALWAYS",
        19: "ALWAYS",
        20: "SOMETIMES",
        21: "NEVER",
        22: "NEVER",
        23: "NEVER",
        24: "NEVER",
        25: "NEVER",
    }


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


def test_faint_synthetic_marks_are_read_correctly() -> None:
    response = analyze_image_bytes(image_bytes("filled-faint-marks.png"))
    answer = {answer.questionNo: answer for answer in response.answers}[5]
    assert response.status == "OK"
    assert answer.status == "OK"
    assert answer.value == "SOMETIMES"


@pytest.mark.parametrize("style", ["tick", "x", "partial"])
def test_child_style_marks_are_read_correctly(style: str) -> None:
    expected = json.loads((ROOT / "sample-forms" / "expected-results.json").read_text(encoding="utf-8"))["filled-clean.png"]
    response = analyze_image_bytes(child_marked_image_bytes(style))
    values = {str(answer.questionNo): answer.value for answer in response.answers}
    assert response.status == "OK"
    assert values == expected


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


def test_healthy_nutrition_v2_template_has_26_four_option_questions() -> None:
    from app.template import load_templates

    template = next(item for item in load_templates() if item["templateCode"] == "HEALTHY_NUTRITION_V2")
    assert template["questionCount"] == 26
    assert [question["questionNo"] for question in template["questions"]] == list(range(1, 27))
    assert all(list(question["options"]) == ["NEVER", "SOMETIMES", "OFTEN", "ALWAYS"] for question in template["questions"])


def test_nutrition_form_is_found_in_landscape_camera_frame() -> None:
    form = cv2.imread(str(SAMPLE_FORMS_DIR / "healthy-nutrition-v1.png"))
    target_height = 760
    target_width = round(form.shape[1] * target_height / form.shape[0])
    resized = cv2.resize(form, (target_width, target_height), interpolation=cv2.INTER_AREA)
    camera_frame = np.full((1080, 1920, 3), 35, dtype=np.uint8)
    x = (camera_frame.shape[1] - target_width) // 2
    y = (camera_frame.shape[0] - target_height) // 2
    camera_frame[y : y + target_height, x : x + target_width] = resized

    source, _ = _find_warp_source(
        camera_frame,
        {"pageWidth": 2480, "pageHeight": 3508},
    )
    assert source.shape == (4, 2)

