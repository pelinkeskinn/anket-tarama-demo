from __future__ import annotations

import time
import uuid
from typing import Any

import cv2
import numpy as np

from app.config import (
    DOUBLE_MARK_THRESHOLD,
    EMPTY_THRESHOLD,
    MARK_THRESHOLD,
    MAX_MANUAL_REVIEW_QUESTIONS,
    MAX_UPLOAD_BYTES,
    UNCERTAIN_MARGIN,
)
from app.errors import OmrError
from app.models import AnalyzeResponse, AnswerResult, ProcessingStats
from app.template import load_template


OPTION_ORDER = ("NEVER", "SOMETIMES", "ALWAYS")


def analyze_image_bytes(image_bytes: bytes) -> AnalyzeResponse:
    if not image_bytes or len(image_bytes) > MAX_UPLOAD_BYTES:
        raise OmrError("INVALID_FILE")

    start = time.perf_counter()
    image = _decode_image(image_bytes)
    _validate_quality(image)

    perspective_start = time.perf_counter()
    template = load_template()
    warped = _warp_to_template(image, template)
    perspective_ms = _elapsed_ms(perspective_start)

    omr_start = time.perf_counter()
    answers = _read_answers(warped, template)
    omr_ms = _elapsed_ms(omr_start)

    review_required_count = sum(1 for answer in answers if answer.status in {"DOUBLE_MARK", "UNCERTAIN"})
    blank_count = sum(1 for answer in answers if answer.status == "BLANK")
    form_confidence = _form_confidence(answers)
    status = "OK"
    if review_required_count > MAX_MANUAL_REVIEW_QUESTIONS:
        status = "TOO_MANY_UNCERTAIN"
    elif review_required_count > 0:
        status = "REVIEW_REQUIRED"

    return AnalyzeResponse(
        analysisId=f"demo-{uuid.uuid4().hex[:12]}",
        templateCode=str(template["templateCode"]),
        status=status,
        formConfidence=form_confidence,
        blankCount=blank_count,
        reviewRequiredCount=review_required_count,
        answers=answers,
        processing=ProcessingStats(totalMs=_elapsed_ms(start), perspectiveMs=perspective_ms, omrMs=omr_ms),
    )


def _decode_image(image_bytes: bytes) -> np.ndarray:
    data = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise OmrError("INVALID_FILE")
    return image


def _validate_quality(image: np.ndarray) -> None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if float(np.mean(gray)) < 55:
        raise OmrError("IMAGE_TOO_DARK")
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur_score < 4:
        raise OmrError("IMAGE_BLURRY")


def _warp_to_template(image: np.ndarray, template: dict[str, Any]) -> np.ndarray:
    marker_centers = _find_marker_centers(image)
    marker_size = float(template["markerSize"])
    marker_margin = float(template["markerMargin"])
    page_width = float(template["pageWidth"])
    page_height = float(template["pageHeight"])
    half = marker_size / 2
    destination = np.array(
        [
            [marker_margin + half, marker_margin + half],
            [page_width - marker_margin - half, marker_margin + half],
            [page_width - marker_margin - half, page_height - marker_margin - half],
            [marker_margin + half, page_height - marker_margin - half],
        ],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(marker_centers, destination)
    return cv2.warpPerspective(image, transform, (int(page_width), int(page_height)))


def _find_marker_centers(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresholded = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    height, width = gray.shape
    min_area = max(800, width * height * 0.0002)
    candidates: list[tuple[float, float, float]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        aspect = w / max(h, 1)
        fill = area / max(w * h, 1)
        if 0.65 <= aspect <= 1.35 and fill > 0.55:
            candidates.append((x + w / 2, y + h / 2, area))

    if len(candidates) < 4:
        raise OmrError("MARKERS_NOT_FOUND")

    centers = np.array([[x, y] for x, y, _ in sorted(candidates, key=lambda item: item[2], reverse=True)[:12]])
    ordered = np.array(
        [
            centers[np.argmin(centers[:, 0] + centers[:, 1])],
            centers[np.argmax(centers[:, 0] - centers[:, 1])],
            centers[np.argmax(centers[:, 0] + centers[:, 1])],
            centers[np.argmin(centers[:, 0] - centers[:, 1])],
        ],
        dtype=np.float32,
    )
    if len({tuple(point) for point in ordered}) < 4:
        raise OmrError("MARKERS_NOT_FOUND")
    return ordered


def _read_answers(warped: np.ndarray, template: dict[str, Any]) -> list[AnswerResult]:
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    answers: list[AnswerResult] = []
    for question in template["questions"]:
        densities = {
            option: _mark_density(gray, box)
            for option, box in question["options"].items()
            if option in OPTION_ORDER
        }
        answers.append(_decide_question(int(question["questionNo"]), densities))
    return answers


def _mark_density(gray: np.ndarray, box: dict[str, int]) -> float:
    x, y, width, height = int(box["x"]), int(box["y"]), int(box["width"]), int(box["height"])
    roi = gray[y : y + height, x : x + width]
    if roi.size == 0:
        return 0.0

    yy, xx = np.ogrid[:height, :width]
    radius = min(width, height) * 0.34
    mask = (xx - width / 2) ** 2 + (yy - height / 2) ** 2 <= radius**2
    center = roi[mask]
    darkness = (255.0 - center.astype(np.float32)) / 255.0
    return round(float(np.clip(np.mean(darkness), 0, 1)), 4)


def _decide_question(question_no: int, densities: dict[str, float]) -> AnswerResult:
    ranked = sorted(densities.items(), key=lambda item: item[1], reverse=True)
    top_option, top_density = ranked[0]
    second_density = ranked[1][1]
    marked = [option for option, density in ranked if density >= DOUBLE_MARK_THRESHOLD]

    if len(marked) >= 2:
        return AnswerResult(questionNo=question_no, value=None, confidence=_double_confidence(ranked), source="UNRESOLVED", status="DOUBLE_MARK")

    if top_density < EMPTY_THRESHOLD:
        confidence = min(1.0, 1.0 - top_density / max(EMPTY_THRESHOLD, 0.01))
        return AnswerResult(questionNo=question_no, value="BLANK", confidence=round(confidence, 3), source="AUTO", status="BLANK")

    if top_density < MARK_THRESHOLD or (top_density - second_density) < UNCERTAIN_MARGIN:
        confidence = min(0.69, max(0.35, top_density))
        return AnswerResult(questionNo=question_no, value=None, confidence=round(confidence, 3), source="UNRESOLVED", status="UNCERTAIN")

    confidence = min(1.0, 0.72 + (top_density - MARK_THRESHOLD) * 0.45 + (top_density - second_density) * 0.35)
    return AnswerResult(questionNo=question_no, value=top_option, confidence=round(confidence, 3), source="AUTO", status="OK")


def _double_confidence(ranked: list[tuple[str, float]]) -> float:
    first = ranked[0][1]
    second = ranked[1][1]
    return round(max(0.2, min(0.72, 0.72 - abs(first - second))), 3)


def _form_confidence(answers: list[AnswerResult]) -> float:
    if not answers:
        return 0.0
    score = 0.0
    for answer in answers:
        penalty = 1.0
        if answer.status == "DOUBLE_MARK":
            penalty = 0.35
        elif answer.status == "UNCERTAIN":
            penalty = 0.5
        elif answer.status == "BLANK":
            penalty = 0.9
        score += answer.confidence * penalty
    return round(max(0.0, min(1.0, score / len(answers))), 3)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)

