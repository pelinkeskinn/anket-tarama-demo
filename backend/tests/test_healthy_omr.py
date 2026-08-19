from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest

from app.errors import OmrError
from app.healthy_omr import (
    OPTION_ORDER,
    calculate_fill_features,
    evaluate_question,
    generate_debug_images,
    read_answers,
    template_match_score,
)
from app.omr import _decode_image, _find_warp_source, _scaled_template, _warp_to_template, analyze_image_bytes
from app.template import load_templates


def healthy_template(code: str = "HEALTHY_NUTRITION_V1") -> dict:
    return next(template for template in load_templates() if template["templateCode"] == code)


def canonical_blank_form(template: dict | None = None) -> np.ndarray:
    template = template or healthy_template()
    image = np.full((template["pageHeight"], template["pageWidth"], 3), 255, dtype=np.uint8)
    marker_size = int(template["markerSize"])
    for point in template["markerCenters"].values():
        center = (round(point["x"]), round(point["y"]))
        half = marker_size // 2
        cv2.rectangle(image, (center[0] - half, center[1] - half), (center[0] + half, center[1] + half), (0, 0, 0), -1)
    for band in template["sectionBands"]:
        cv2.rectangle(
            image,
            (int(band["x"]), int(band["y"])),
            (int(band["x"] + band["width"]), int(band["y"] + band["height"])),
            (20, 20, 175),
            -1,
        )
    for question in template["questions"]:
        for box in question["options"].values():
            center = (int(box["x"]) + int(box["width"]) // 2, int(box["y"]) + int(box["height"]) // 2)
            radius = round(min(int(box["width"]), int(box["height"])) * 0.392)
            cv2.circle(image, center, radius, (0, 0, 0), 4)
    return image


def marked_roi(style: str) -> tuple[np.ndarray, dict[str, int]]:
    image = np.full((100, 100), 255, dtype=np.uint8)
    box = {"x": 12, "y": 12, "width": 76, "height": 76}
    center = (50, 50)
    cv2.circle(image, center, 30, 0, 4)
    if style == "filled":
        cv2.circle(image, center, 24, 110, -1)
    elif style == "tick":
        cv2.line(image, (32, 62), (47, 75), 0, 7)
        cv2.line(image, (47, 75), (75, 30), 0, 7)
    elif style == "x":
        cv2.line(image, (30, 30), (70, 70), 0, 7)
        cv2.line(image, (70, 30), (30, 70), 0, 7)
    elif style == "line":
        cv2.line(image, (28, 68), (72, 32), 0, 7)
    elif style == "half":
        cv2.ellipse(image, center, (24, 24), 0, 0, 180, 0, -1)
    elif style == "dot":
        cv2.circle(image, center, 7, 0, -1)
    elif style != "blank":
        raise ValueError(style)
    return image, box


def test_reference_geometry_contains_exactly_104_ordered_rois() -> None:
    template = healthy_template()
    assert template["sourceSha256"] == "4b89b451499fd9270bda9e9118bcbffc52124a5b2f726fde7f5ce27531ed8b8c"
    assert template["questionCount"] == 26
    assert sum(len(question["options"]) for question in template["questions"]) == 104
    assert [question["section"] for question in template["questions"][:11]] == [1] * 11
    assert [question["section"] for question in template["questions"][11:]] == [2] * 15
    for question in template["questions"]:
        boxes = [question["options"][option] for option in OPTION_ORDER]
        assert [box["x"] for box in boxes] == sorted(box["x"] for box in boxes)
        assert all(0 <= box["x"] < template["pageWidth"] and 0 <= box["y"] < template["pageHeight"] for box in boxes)


def test_revised_reference_geometry_contains_104_rois() -> None:
    template = healthy_template("HEALTHY_NUTRITION_V2")
    assert template["sourceSha256"] == "dbe1b14d424c4af12a81a45aac3f88075ac4842f241da1e419f9b1fc74dad103"
    assert template["questionCount"] == 26
    assert sum(len(question["options"]) for question in template["questions"]) == 104
    assert [question["section"] for question in template["questions"][:11]] == [1] * 11
    assert [question["section"] for question in template["questions"][11:]] == [2] * 15


def test_answers_expose_labels_from_the_matched_form_template() -> None:
    template = healthy_template("HEALTHY_NUTRITION_V2")
    answers = read_answers(cv2.cvtColor(canonical_blank_form(template), cv2.COLOR_BGR2GRAY), template)

    assert answers[0].optionLabels == ["Hiçbir Zaman", "Ara Sıra", "Sık Sık", "Her Zaman"]
    assert answers[11].optionLabels == ["Hiçbir Zaman", "1-2 Kez/Hafta", "3-4 Kez/Hafta", "5+ Kez/Hafta"]


def test_circle_grid_selects_the_correct_pdf_revision() -> None:
    original = healthy_template("HEALTHY_NUTRITION_V1")
    revised = healthy_template("HEALTHY_NUTRITION_V2")
    original_form = canonical_blank_form(original)
    revised_form = canonical_blank_form(revised)
    assert template_match_score(original_form, original) >= 0.90
    assert template_match_score(original_form, revised) < 0.68
    assert template_match_score(revised_form, revised) >= 0.90
    assert template_match_score(revised_form, original) < 0.68


@pytest.mark.parametrize(
    ("style", "expected_status"),
    [
        ("filled", "MARKED"),
        ("blank", "BLANK"),
        ("tick", "MARKED"),
        ("x", "MARKED"),
        ("line", "MARKED"),
        ("half", "MARKED"),
        ("dot", "MARKED"),
    ],
)
def test_strict_mark_classifier_obeys_form_rules(style: str, expected_status: str) -> None:
    question = healthy_template()["questions"][0]
    marked_image, box = marked_roi(style)
    blank_image, blank_box = marked_roi("blank")
    features = [calculate_fill_features(marked_image, box)] + [calculate_fill_features(blank_image, blank_box)] * 3
    answer = evaluate_question(question, features)
    assert answer.status == expected_status


def test_two_filled_options_are_multiple() -> None:
    question = healthy_template()["questions"][0]
    marked_image, marked_box = marked_roi("filled")
    blank_image, blank_box = marked_roi("blank")
    filled = calculate_fill_features(marked_image, marked_box)
    blank = calculate_fill_features(blank_image, blank_box)
    answer = evaluate_question(question, [filled, blank, filled, blank])
    assert answer.status == "MULTIPLE"
    assert answer.value is None


def test_two_irregular_marks_are_multiple() -> None:
    question = healthy_template()["questions"][0]
    tick_image, tick_box = marked_roi("tick")
    cross_image, cross_box = marked_roi("x")
    blank_image, blank_box = marked_roi("blank")
    tick = calculate_fill_features(tick_image, tick_box)
    cross = calculate_fill_features(cross_image, cross_box)
    blank = calculate_fill_features(blank_image, blank_box)
    answer = evaluate_question(question, [tick, blank, cross, blank])
    assert answer.status == "MULTIPLE"
    assert answer.value is None


def test_invalid_and_multiple_answers_require_review_in_full_analysis() -> None:
    template = healthy_template()
    form = canonical_blank_form()

    def center(question_no: int, option: str) -> tuple[int, int]:
        box = template["questions"][question_no - 1]["options"][option]
        return int(box["x"]) + int(box["width"]) // 2, int(box["y"]) + int(box["height"]) // 2

    cv2.circle(form, center(1, "NEVER"), 24, (70, 70, 70), -1)
    for question_no in (2, 3, 4):
        point = center(question_no, "SOMETIMES")
        cv2.line(form, (point[0] - 20, point[1] + 17), (point[0] + 20, point[1] - 17), (0, 0, 0), 7)
    cv2.circle(form, center(5, "NEVER"), 24, (60, 60, 60), -1)
    cv2.circle(form, center(5, "OFTEN"), 24, (60, 60, 60), -1)

    success, encoded = cv2.imencode(".png", form)
    assert success
    response = analyze_image_bytes(encoded.tobytes())
    answers = {answer.questionNo: answer for answer in response.answers}
    assert response.templateCode == "HEALTHY_NUTRITION_V1"
    assert response.status == "REVIEW_REQUIRED"
    assert response.reviewRequiredCount == 1
    assert answers[1].status == "MARKED"
    assert [answers[number].status for number in (2, 3, 4)] == ["MARKED"] * 3
    assert answers[5].status == "MULTIPLE"


def test_many_uncertain_healthy_answers_stay_available_for_manual_review() -> None:
    template = healthy_template()
    form = canonical_blank_form()

    for question_no in range(1, 7):
        question = template["questions"][question_no - 1]
        for option in ("NEVER", "OFTEN"):
            box = question["options"][option]
            center = (int(box["x"]) + int(box["width"]) // 2, int(box["y"]) + int(box["height"]) // 2)
            cv2.circle(form, center, 24, (60, 60, 60), -1)

    success, encoded = cv2.imencode(".png", form)
    assert success
    response = analyze_image_bytes(encoded.tobytes())

    assert response.templateCode == "HEALTHY_NUTRITION_V1"
    assert response.reviewRequiredCount == 6
    assert response.status == "REVIEW_REQUIRED"


def test_template_similarity_validates_circle_grid_and_section_bands() -> None:
    template = healthy_template()
    assert template_match_score(canonical_blank_form(), template) >= 0.90
    shifted = np.roll(canonical_blank_form(), 95, axis=1)
    assert template_match_score(shifted, template) < 0.68


def test_perspective_alignment_restores_reference_grid() -> None:
    template = healthy_template()
    original = canonical_blank_form()
    destination = np.float32([[120, 80], [2250, 20], [2380, 3420], [40, 3360]])
    source = np.float32([[0, 0], [2479, 0], [2479, 3507], [0, 3507]])
    transform = cv2.getPerspectiveTransform(source, destination)
    photographed = cv2.warpPerspective(original, transform, (2480, 3508), borderValue=(45, 45, 45))
    reading_template = _scaled_template(template, 0.8)
    warp_source = _find_warp_source(photographed, template)
    aligned = _warp_to_template(photographed, reading_template, warp_source)
    assert template_match_score(aligned, reading_template) >= 0.85


def test_single_page_pdf_is_rasterized_to_canonical_size() -> None:
    document = pymupdf.open()
    document.new_page(width=595.2756, height=841.8898)
    pdf_bytes = document.write()
    document.close()
    image = _decode_image(pdf_bytes)
    assert image.shape[:2] == (3508, 2480)


def test_pdf_analysis_does_not_try_rotated_orientations(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.omr as omr_module

    document = pymupdf.open()
    page = document.new_page(width=595.2756, height=841.8898)
    page.insert_text((72, 72), "not the canonical survey")
    pdf_bytes = document.write()
    document.close()

    def fail_if_called(_image: np.ndarray) -> list[np.ndarray]:
        raise AssertionError("PDF analysis must not generate rotated image candidates")

    monkeypatch.setattr(omr_module, "_orientation_candidates", fail_if_called)
    with pytest.raises(OmrError):
        omr_module.analyze_image_bytes(pdf_bytes)


def test_debug_images_include_all_required_stages(tmp_path: Path) -> None:
    template = healthy_template()
    form = canonical_blank_form()
    answers = read_answers(cv2.cvtColor(form, cv2.COLOR_BGR2GRAY), template)
    marker_source = np.float32(
        [
            [191.5, 158.5],
            [2288.5, 158.5],
            [2288.5, 3399.5],
            [191.5, 3399.5],
        ]
    )
    output = generate_debug_images(form, form, marker_source, template, answers, "test-analysis", tmp_path)
    assert {path.name for path in output.iterdir()} == {
        "01_original.jpg",
        "03_markers_detected.jpg",
        "04_perspective_corrected.jpg",
        "05_template_aligned.jpg",
        "06_answer_rois.jpg",
        "07_thresholded_rois.png",
        "08_final_result.jpg",
    }
