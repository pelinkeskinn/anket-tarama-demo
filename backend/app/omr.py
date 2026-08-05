from __future__ import annotations

import time
import uuid
from io import BytesIO
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

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
from app.template import load_templates


OPTION_ORDER = ("NEVER", "SOMETIMES", "ALWAYS")


def analyze_image_bytes(image_bytes: bytes) -> AnalyzeResponse:
    if not image_bytes or len(image_bytes) > MAX_UPLOAD_BYTES:
        raise OmrError("INVALID_FILE")

    start = time.perf_counter()
    image = _decode_image(image_bytes)
    _validate_quality(image)

    candidates: list[tuple[dict[str, Any], list[AnswerResult], int, int]] = []
    for oriented_image in _orientation_candidates(image):
        for template in load_templates():
            try:
                candidates.append(_analyze_template(oriented_image, template))
            except OmrError as exc:
                if exc.code != "MARKERS_NOT_FOUND":
                    raise
    if not candidates:
        raise OmrError("MARKERS_NOT_FOUND")
    template, answers, perspective_ms, omr_ms = max(candidates, key=_analysis_score)

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


def _analyze_template(image: np.ndarray, template: dict[str, Any]) -> tuple[dict[str, Any], list[AnswerResult], int, int]:
    perspective_start = time.perf_counter()
    warped = _warp_to_template(image, template)
    perspective_ms = _elapsed_ms(perspective_start)

    omr_start = time.perf_counter()
    answers = _read_answers(warped, template)
    omr_ms = _elapsed_ms(omr_start)
    return template, answers, perspective_ms, omr_ms


def _analysis_score(candidate: tuple[dict[str, Any], list[AnswerResult], int, int]) -> tuple[float, int]:
    _, answers, _, _ = candidate
    review_required_count = sum(1 for answer in answers if answer.status in {"DOUBLE_MARK", "UNCERTAIN"})
    return (_form_confidence(answers), -review_required_count)


def _decode_image(image_bytes: bytes) -> np.ndarray:
    try:
        with Image.open(BytesIO(image_bytes)) as pil_image:
            corrected = ImageOps.exif_transpose(pil_image).convert("RGB")
            image = cv2.cvtColor(np.array(corrected), cv2.COLOR_RGB2BGR)
    except (OSError, UnidentifiedImageError) as exc:
        raise OmrError("INVALID_FILE") from exc

    if image.size == 0:
        raise OmrError("INVALID_FILE")
    return image


def _orientation_candidates(image: np.ndarray) -> list[np.ndarray]:
    return [
        image,
        cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE),
        cv2.rotate(image, cv2.ROTATE_180),
        cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE),
    ]


def _validate_quality(image: np.ndarray) -> None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if float(np.mean(gray)) < 55:
        raise OmrError("IMAGE_TOO_DARK")
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur_score < 4:
        raise OmrError("IMAGE_BLURRY")


def _warp_to_template(image: np.ndarray, template: dict[str, Any]) -> np.ndarray:
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
    try:
        source = _find_marker_centers(image)
    except OmrError:
        source = _find_page_corners(image, page_width / page_height)
        destination = np.array(
            [
                [0, 0],
                [page_width, 0],
                [page_width, page_height],
                [0, page_height],
            ],
            dtype=np.float32,
        )

    transform = cv2.getPerspectiveTransform(source, destination)
    return cv2.warpPerspective(image, transform, (int(page_width), int(page_height)))


def _find_marker_centers(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    height, width = gray.shape
    min_area = max(120, width * height * 0.000025)

    marker_sets: list[np.ndarray] = []
    for thresholded in _marker_thresholds(blurred):
        candidates = _marker_candidates(thresholded, min_area)
        ordered = _order_marker_candidates(candidates, width / max(height, 1))
        if ordered is not None:
            marker_sets.append(ordered)

    if marker_sets:
        return max(marker_sets, key=_quadrilateral_bbox_area)

    raise OmrError("MARKERS_NOT_FOUND")


def _marker_thresholds(gray: np.ndarray) -> list[np.ndarray]:
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        51,
        9,
    )
    kernel = np.ones((3, 3), np.uint8)
    return [
        otsu,
        cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel, iterations=1),
        adaptive,
        cv2.morphologyEx(adaptive, cv2.MORPH_CLOSE, kernel, iterations=1),
    ]


def _marker_candidates(thresholded: np.ndarray, min_area: float) -> list[tuple[float, float, float]]:
    contours, _ = cv2.findContours(thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[float, float, float]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        aspect = w / max(h, 1)
        fill = area / max(w * h, 1)
        if 0.5 <= aspect <= 1.55 and fill > 0.4:
            candidates.append((x + w / 2, y + h / 2, area))
    return candidates


def _order_marker_candidates(candidates: list[tuple[float, float, float]], image_aspect: float) -> np.ndarray | None:
    if len(candidates) < 4:
        return None

    centers = np.array([[x, y] for x, y, _ in sorted(candidates, key=lambda item: item[2], reverse=True)[:240]])
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
        return None
    quad_aspect = _quadrilateral_aspect(ordered)
    target_aspect = 1 / image_aspect if image_aspect > 1 else image_aspect
    if abs(quad_aspect - target_aspect) / max(target_aspect, 0.01) > 0.28:
        return None
    if not _has_consistent_edges(ordered):
        return None
    return ordered


def _quadrilateral_aspect(points: np.ndarray) -> float:
    top_width = float(np.linalg.norm(points[1] - points[0]))
    bottom_width = float(np.linalg.norm(points[2] - points[3]))
    left_height = float(np.linalg.norm(points[3] - points[0]))
    right_height = float(np.linalg.norm(points[2] - points[1]))
    return ((top_width + bottom_width) / 2) / max((left_height + right_height) / 2, 1)


def _quadrilateral_bbox_area(points: np.ndarray) -> float:
    return float((np.max(points[:, 0]) - np.min(points[:, 0])) * (np.max(points[:, 1]) - np.min(points[:, 1])))


def _has_consistent_edges(points: np.ndarray) -> bool:
    top_width = float(np.linalg.norm(points[1] - points[0]))
    bottom_width = float(np.linalg.norm(points[2] - points[3]))
    left_height = float(np.linalg.norm(points[3] - points[0]))
    right_height = float(np.linalg.norm(points[2] - points[1]))
    width_ratio = max(top_width, bottom_width) / max(min(top_width, bottom_width), 1)
    height_ratio = max(left_height, right_height) / max(min(left_height, right_height), 1)
    return width_ratio <= 1.35 and height_ratio <= 1.35


def _find_page_corners(image: np.ndarray, target_aspect: float) -> np.ndarray:
    height, width = image.shape[:2]
    aspect = width / max(height, 1)
    if abs(aspect - target_aspect) / target_aspect <= 0.18:
        return np.array(
            [
                [0, 0],
                [width - 1, 0],
                [width - 1, height - 1],
                [0, height - 1],
            ],
            dtype=np.float32,
        )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresholded = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        51,
        7,
    )
    contours, _ = cv2.findContours(thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = width * height
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:10]:
        area = float(cv2.contourArea(contour))
        if area < image_area * 0.2:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(polygon) != 4:
            continue
        corners = polygon.reshape(4, 2).astype(np.float32)
        return _order_points(corners)

    raise OmrError("MARKERS_NOT_FOUND")


def _order_points(points: np.ndarray) -> np.ndarray:
    return np.array(
        [
            points[np.argmin(points[:, 0] + points[:, 1])],
            points[np.argmax(points[:, 0] - points[:, 1])],
            points[np.argmax(points[:, 0] + points[:, 1])],
            points[np.argmin(points[:, 0] - points[:, 1])],
        ],
        dtype=np.float32,
    )


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
    distance = (xx - width / 2) ** 2 + (yy - height / 2) ** 2
    center_radius = min(width, height) * 0.28
    background_radius = min(width, height) * 0.45
    center = roi[distance <= center_radius**2]
    background = roi[distance >= background_radius**2]
    if center.size == 0 or background.size == 0:
        return 0.0

    center_darkness = float(np.mean((255.0 - center.astype(np.float32)) / 255.0))
    background_darkness = float(np.median((255.0 - background.astype(np.float32)) / 255.0))
    normalized = (center_darkness - background_darkness) / max(1.0 - background_darkness, 0.01)
    return round(float(np.clip(normalized, 0, 1)), 4)


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

