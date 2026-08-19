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
    OMR_DEBUG_DIR,
    OMR_DEBUG_ENABLED,
    UNCERTAIN_MARGIN,
)
from app.errors import OmrError
from app.healthy_omr import generate_debug_images, is_healthy_template, read_answers as read_healthy_answers, template_match_score
from app.models import AnalyzeResponse, AnswerResult, ProcessingStats
from app.template import load_templates


OPTION_ORDER = ("NEVER", "SOMETIMES", "OFTEN", "ALWAYS")
MAX_ACCEPTED_BLANK_ANSWERS = 8
LOW_CONTRAST_MARK_THRESHOLD = 0.12
ANALYSIS_SCALE = 0.8
OK_STATUSES = {"OK", "MARKED"}
REVIEW_STATUSES = {"DOUBLE_MARK", "UNCERTAIN", "MULTIPLE", "INVALID", "AMBIGUOUS"}


def analyze_image_bytes(
    image_bytes: bytes,
    template_hint: str | None = None,
    guided_capture: bool = False,
) -> AnalyzeResponse:
    if not image_bytes or len(image_bytes) > MAX_UPLOAD_BYTES:
        raise OmrError("INVALID_FILE")

    start = time.perf_counter()
    analysis_id = f"demo-{uuid.uuid4().hex[:12]}"
    image = _decode_image(image_bytes)
    _validate_quality(image)

    is_pdf = image_bytes.startswith(b"%PDF")
    candidates: list[tuple[np.ndarray, dict[str, Any], list[AnswerResult], int, int, tuple[np.ndarray, bool]]] = []
    saw_invalid_template = False
    templates = load_templates()
    is_guided_nutrition_scan = template_hint == "HEALTHY_NUTRITION"
    if is_pdf or is_guided_nutrition_scan:
        templates = [template for template in templates if is_healthy_template(template)]
    healthy_match_threshold = 0.18 if guided_capture and is_guided_nutrition_scan else 0.30 if is_guided_nutrition_scan else 0.68
    # PDF pages are rasterized by their page coordinate system and are already
    # upright. Trying four rotations multiplies Render CPU time and can push a
    # valid request beyond the reverse proxy timeout.
    oriented_images = [image] if is_pdf or guided_capture else _orientation_candidates(image)
    for oriented_image in oriented_images:
        warp_sources: dict[float, tuple[np.ndarray, bool]] = {}
        matched_healthy_template = False
        for template in templates:
            try:
                aspect_key = round(float(template["pageWidth"]) / float(template["pageHeight"]), 4)
                if aspect_key not in warp_sources:
                    warp_sources[aspect_key] = (
                        _pdf_page_corners(oriented_image)
                        if is_pdf or guided_capture
                        else _find_warp_source(oriented_image, template)
                    )
                try:
                    template_result, answers, perspective_ms, omr_ms = _analyze_template(
                        oriented_image, template, warp_sources[aspect_key], healthy_match_threshold
                    )
                except OmrError as exc:
                    # A PDF page normally already is the normalized sheet. If
                    # its contents came from a skewed scan, fall back to the
                    # slower marker/page detector instead of rejecting it.
                    if not (is_pdf or guided_capture) or exc.code != "INVALID_TEMPLATE":
                        raise
                    detected_source = _find_warp_source(oriented_image, template)
                    warp_sources[aspect_key] = detected_source
                    template_result, answers, perspective_ms, omr_ms = _analyze_template(
                        oriented_image, template, detected_source, healthy_match_threshold
                    )
                candidates.append((oriented_image, template_result, answers, perspective_ms, omr_ms, warp_sources[aspect_key]))
                if is_healthy_template(template_result) and float(template_result.get("_matchScore", 0.0)) >= 0.72:
                    matched_healthy_template = True
                    break
            except OmrError as exc:
                saw_invalid_template = saw_invalid_template or exc.code == "INVALID_TEMPLATE"
                if exc.code not in {"MARKERS_NOT_FOUND", "ALIGNMENT_FAILED", "INVALID_TEMPLATE"}:
                    raise
        # A calibrated circle-grid match is stronger evidence than results from
        # unrelated generic templates. Once found, avoid three more rotations
        # and the remaining template passes.
        if matched_healthy_template:
            break
    if not candidates:
        raise OmrError("INVALID_TEMPLATE" if saw_invalid_template else "ALIGNMENT_FAILED")
    selected_image, template, answers, perspective_ms, omr_ms, selected_warp_source = max(candidates, key=_analysis_score)
    if _needs_robust_read(answers):
        robust_start = time.perf_counter()
        reading_template = _scaled_template(template, ANALYSIS_SCALE)
        robust_answers = _read_answers_robust(
            _warp_to_template(selected_image, reading_template, selected_warp_source), reading_template
        )
        robust_ms = _elapsed_ms(robust_start)
        if _analysis_score((selected_image, template, robust_answers, perspective_ms, omr_ms, selected_warp_source)) > _analysis_score(
            (selected_image, template, answers, perspective_ms, omr_ms, selected_warp_source)
        ):
            answers = robust_answers
            omr_ms += robust_ms

    review_required_count = sum(1 for answer in answers if answer.status in REVIEW_STATUSES)
    blank_count = sum(1 for answer in answers if answer.status == "BLANK")
    form_confidence = _form_confidence(answers)
    status = "OK"
    # The calibrated nutrition form can safely expose every unresolved answer
    # for manual correction. Do not discard the entire scan merely because
    # more than four hand-written marks need confirmation.
    if not is_healthy_template(template) and (
        review_required_count > MAX_MANUAL_REVIEW_QUESTIONS or blank_count > MAX_ACCEPTED_BLANK_ANSWERS
    ):
        status = "TOO_MANY_UNCERTAIN"
    elif review_required_count > 0:
        status = "REVIEW_REQUIRED"

    if OMR_DEBUG_ENABLED and is_healthy_template(template):
        debug_source = selected_warp_source[0]
        debug_template = _scaled_template(template, ANALYSIS_SCALE)
        debug_warped = _warp_to_template(selected_image, debug_template, selected_warp_source)
        generate_debug_images(selected_image, debug_warped, debug_source, debug_template, answers, analysis_id, OMR_DEBUG_DIR)

    return AnalyzeResponse(
        analysisId=analysis_id,
        templateCode=str(template["templateCode"]),
        status=status,
        formConfidence=form_confidence,
        blankCount=blank_count,
        reviewRequiredCount=review_required_count,
        answers=answers,
        processing=ProcessingStats(totalMs=_elapsed_ms(start), perspectiveMs=perspective_ms, omrMs=omr_ms),
    )


def _analyze_template(
    image: np.ndarray,
    template: dict[str, Any],
    warp_source: tuple[np.ndarray, bool] | None = None,
    healthy_match_threshold: float = 0.68,
) -> tuple[dict[str, Any], list[AnswerResult], int, int]:
    reading_template = _scaled_template(template, ANALYSIS_SCALE)
    perspective_start = time.perf_counter()
    warped = _warp_to_template(image, reading_template, warp_source)
    perspective_ms = _elapsed_ms(perspective_start)

    omr_start = time.perf_counter()
    template_result = template
    if is_healthy_template(reading_template):
        match_score = template_match_score(warped, reading_template)
        if match_score < healthy_match_threshold:
            raise OmrError("INVALID_TEMPLATE")
        template_result = {**template, "_matchScore": match_score}
    answers = _read_answers(warped, reading_template)
    omr_ms = _elapsed_ms(omr_start)
    return template_result, answers, perspective_ms, omr_ms


def _analysis_score(candidate: tuple[Any, ...]) -> tuple[float, float, float, float]:
    # Internal reading variants use the original five-field tuple while the
    # top-level candidates also carry their reusable warp source.
    template = candidate[1]
    answers = candidate[2]
    answer_count = max(len(answers), 1)
    ok_count = sum(1 for answer in answers if answer.status in OK_STATUSES)
    review_required_count = sum(1 for answer in answers if answer.status in REVIEW_STATUSES)
    blank_count = sum(1 for answer in answers if answer.status == "BLANK")
    # Template/orientation selection must be driven by answers for which actual
    # mark evidence was found.  A blank answer can legitimately have confidence
    # 1.0, so putting form confidence first lets a wrong template full of
    # "confident blanks" beat the correct template when marks are light or odd.
    return (
        float(template.get("_matchScore", 0.0)),
        ok_count / answer_count,
        -review_required_count / answer_count,
        _form_confidence(answers) - blank_count / answer_count * 0.1,
    )


def _needs_robust_read(answers: list[AnswerResult]) -> bool:
    uncertain_count = sum(1 for answer in answers if answer.status in REVIEW_STATUSES)
    blank_count = sum(1 for answer in answers if answer.status == "BLANK")
    low_confidence_count = sum(1 for answer in answers if answer.status in OK_STATUSES and answer.confidence < 0.78)
    return uncertain_count > 0 or blank_count > 0 or low_confidence_count > 4


def _decode_image(image_bytes: bytes) -> np.ndarray:
    if image_bytes.startswith(b"%PDF"):
        try:
            import pymupdf

            with pymupdf.open(stream=image_bytes, filetype="pdf") as document:
                if len(document) != 1:
                    raise OmrError("INVALID_FILE")
                page = document[0]
                matrix = pymupdf.Matrix(2480 / page.rect.width, 3508 / page.rect.height)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
                image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except OmrError:
            raise
        except Exception as exc:
            raise OmrError("INVALID_FILE") from exc
        if image.size == 0:
            raise OmrError("INVALID_FILE")
        return image
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


def _pdf_page_corners(image: np.ndarray) -> tuple[np.ndarray, bool]:
    height, width = image.shape[:2]
    return (
        np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32),
        True,
    )


def _validate_quality(image: np.ndarray) -> None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if float(np.mean(gray)) < 55:
        raise OmrError("IMAGE_TOO_DARK")
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur_score < 4:
        raise OmrError("IMAGE_BLURRY")


def _warp_to_template(image: np.ndarray, template: dict[str, Any], warp_source: tuple[np.ndarray, bool] | None = None) -> np.ndarray:
    marker_size = float(template["markerSize"])
    marker_margin = float(template["markerMargin"])
    page_width = float(template["pageWidth"])
    page_height = float(template["pageHeight"])
    half = marker_size / 2
    marker_centers = template.get("markerCenters")
    if isinstance(marker_centers, dict):
        destination = np.array(
            [
                [marker_centers["topLeft"]["x"], marker_centers["topLeft"]["y"]],
                [marker_centers["topRight"]["x"], marker_centers["topRight"]["y"]],
                [marker_centers["bottomRight"]["x"], marker_centers["bottomRight"]["y"]],
                [marker_centers["bottomLeft"]["x"], marker_centers["bottomLeft"]["y"]],
            ],
            dtype=np.float32,
        )
    else:
        destination = np.array(
            [
                [marker_margin + half, marker_margin + half],
                [page_width - marker_margin - half, marker_margin + half],
                [page_width - marker_margin - half, page_height - marker_margin - half],
                [marker_margin + half, page_height - marker_margin - half],
            ],
            dtype=np.float32,
        )
    source, uses_page_corners = warp_source if warp_source is not None else _find_warp_source(image, template)
    if uses_page_corners:
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


def _find_warp_source(image: np.ndarray, template: dict[str, Any]) -> tuple[np.ndarray, bool]:
    page_width = float(template["pageWidth"])
    page_height = float(template["pageHeight"])
    aruco_markers = _find_aruco_marker_centers(image, template)
    if aruco_markers is not None:
        return aruco_markers, False
    try:
        return _find_marker_centers(image, page_width / page_height), False
    except OmrError:
        try:
            return _find_page_corners(image, page_width / page_height), True
        except OmrError:
            try:
                return _find_marker_centers(image, page_width / page_height, allow_small=True), False
            except OmrError as exc:
                raise OmrError("ALIGNMENT_FAILED") from exc


def _find_aruco_marker_centers(image: np.ndarray, template: dict[str, Any]) -> np.ndarray | None:
    marker_ids = template.get("markerIds")
    if not isinstance(marker_ids, dict):
        return None
    aruco = getattr(cv2, "aruco", None)
    if aruco is None:
        return None

    dictionary_name = str(template.get("markerType", "ARUCO_4X4_50"))
    dictionary_id = getattr(aruco, f"DICT_{dictionary_name}", None)
    if dictionary_id is None:
        return None

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dictionary = aruco.getPredefinedDictionary(dictionary_id)
    parameters = aruco.DetectorParameters()
    detector = aruco.ArucoDetector(dictionary, parameters)
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return None

    found: dict[int, np.ndarray] = {}
    for marker_corners, marker_id in zip(corners, ids.flatten()):
        found[int(marker_id)] = np.mean(marker_corners.reshape(4, 2), axis=0).astype(np.float32)

    keys = ("topLeft", "topRight", "bottomRight", "bottomLeft")
    try:
        ordered = np.array([found[int(marker_ids[key])] for key in keys], dtype=np.float32)
    except (KeyError, TypeError, ValueError):
        return None

    if len({tuple(point) for point in ordered}) < 4:
        return None
    if not _has_consistent_edges(ordered):
        return None
    return ordered


def _scaled_template(template: dict[str, Any], scale: float) -> dict[str, Any]:
    if scale == 1:
        return template
    scaled = {
        **template,
        "pageWidth": int(round(float(template["pageWidth"]) * scale)),
        "pageHeight": int(round(float(template["pageHeight"]) * scale)),
        "markerMargin": int(round(float(template["markerMargin"]) * scale)),
        "markerSize": int(round(float(template["markerSize"]) * scale)),
        "questions": [
            {
                **question,
                "options": {
                    option: {
                        "x": int(round(float(box["x"]) * scale)),
                        "y": int(round(float(box["y"]) * scale)),
                        "width": max(1, int(round(float(box["width"]) * scale))),
                        "height": max(1, int(round(float(box["height"]) * scale))),
                    }
                    for option, box in question["options"].items()
                },
            }
            for question in template["questions"]
        ],
    }
    if isinstance(template.get("markerCenters"), dict):
        scaled["markerCenters"] = {
            key: {"x": float(point["x"]) * scale, "y": float(point["y"]) * scale}
            for key, point in template["markerCenters"].items()
        }
    if isinstance(template.get("sectionBands"), list):
        scaled["sectionBands"] = [
            {
                **band,
                "x": int(round(float(band["x"]) * scale)),
                "y": int(round(float(band["y"]) * scale)),
                "width": int(round(float(band["width"]) * scale)),
                "height": int(round(float(band["height"]) * scale)),
            }
            for band in template["sectionBands"]
        ]
    return scaled


def _find_marker_centers(image: np.ndarray, target_aspect: float, allow_small: bool = False) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    height, width = gray.shape
    # Small markers are a last-resort pass because text dots and answer circles
    # become plausible candidates at this scale.
    min_area = max(20, width * height * 0.000004) if allow_small else max(120, width * height * 0.000025)

    all_candidates: list[tuple[float, float, float]] = []
    for thresholded in _marker_thresholds(blurred):
        all_candidates.extend(_marker_candidates(thresholded, min_area))

    candidates: list[tuple[float, float, float]] = []
    for candidate in sorted(all_candidates, key=lambda item: item[2], reverse=True):
        if all((candidate[0] - existing[0]) ** 2 + (candidate[1] - existing[1]) ** 2 > 20**2 for existing in candidates):
            candidates.append(candidate)

    ordered = _order_marker_candidates(candidates, width, height, target_aspect)
    if ordered is not None:
        return ordered

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


def _order_marker_candidates(candidates: list[tuple[float, float, float]], width: int, height: int, target_aspect: float) -> np.ndarray | None:
    if len(candidates) < 4:
        return None

    extreme_ordered = _select_extreme_marker_quad(candidates, width, height, target_aspect)
    if extreme_ordered is not None:
        return extreme_ordered

    corner_ordered = _select_corner_marker_quad(candidates, width, height, target_aspect)
    if corner_ordered is not None:
        return corner_ordered

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
    if abs(quad_aspect - target_aspect) / max(target_aspect, 0.01) > 0.28:
        return None
    if not _has_consistent_edges(ordered):
        return None
    return ordered


def _select_extreme_marker_quad(candidates: list[tuple[float, float, float]], width: int, height: int, target_aspect: float) -> np.ndarray | None:
    centers = np.array([[x, y] for x, y, _ in candidates], dtype=np.float32)
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
    if abs(quad_aspect - target_aspect) / max(target_aspect, 0.01) > 0.22:
        return None
    if not _has_consistent_edges(ordered):
        return None
    if _quadrilateral_bbox_area(ordered) < width * height * 0.08:
        return None
    if not _points_are_near_image_corners(ordered, width, height):
        return None
    return ordered


def _select_corner_marker_quad(candidates: list[tuple[float, float, float]], width: int, height: int, target_aspect: float) -> np.ndarray | None:
    regions = (
        ((0.0, 0.45), (0.0, 0.45), (0.0, 0.0)),
        ((0.55, 1.0), (0.0, 0.45), (1.0, 0.0)),
        ((0.55, 1.0), (0.55, 1.0), (1.0, 1.0)),
        ((0.0, 0.45), (0.55, 1.0), (0.0, 1.0)),
    )
    groups: list[list[tuple[float, float, float]]] = []
    diagonal = float(np.hypot(width, height))
    for (x_range, y_range, corner) in regions:
        region_candidates = [
            candidate
            for candidate in candidates
            if x_range[0] * width <= candidate[0] <= x_range[1] * width
            and y_range[0] * height <= candidate[1] <= y_range[1] * height
        ]
        if not region_candidates:
            return None
        corner_x, corner_y = corner[0] * width, corner[1] * height
        ranked = sorted(
            region_candidates,
            key=lambda item: item[2] * (1.0 + 2.0 * max(0.0, 1.0 - float(np.hypot(item[0] - corner_x, item[1] - corner_y)) / diagonal)),
            reverse=True,
        )
        groups.append(ranked[:8])

    best_score = 0.0
    best_ordered: np.ndarray | None = None
    image_area = width * height
    for top_left in groups[0]:
        for top_right in groups[1]:
            for bottom_right in groups[2]:
                for bottom_left in groups[3]:
                    ordered = np.array(
                        [
                            [top_left[0], top_left[1]],
                            [top_right[0], top_right[1]],
                            [bottom_right[0], bottom_right[1]],
                            [bottom_left[0], bottom_left[1]],
                        ],
                        dtype=np.float32,
                    )
                    if len({tuple(point) for point in ordered}) < 4:
                        continue
                    quad_aspect = _quadrilateral_aspect(ordered)
                    aspect_error = abs(quad_aspect - target_aspect) / max(target_aspect, 0.01)
                    if aspect_error > 0.22 or not _has_consistent_edges(ordered):
                        continue
                    if not _points_are_near_image_corners(ordered, width, height):
                        continue
                    bbox_area = _quadrilateral_bbox_area(ordered)
                    if bbox_area < image_area * 0.08:
                        continue
                    marker_areas = [top_left[2], top_right[2], bottom_right[2], bottom_left[2]]
                    area_ratio = max(marker_areas) / max(min(marker_areas), 1.0)
                    if area_ratio > 5.0:
                        continue
                    score = bbox_area * (1.0 - aspect_error) / (area_ratio**0.35)
                    if score > best_score:
                        best_score = score
                        best_ordered = ordered
    return best_ordered


def _points_are_near_image_corners(points: np.ndarray, width: int, height: int) -> bool:
    return bool(
        points[0][0] <= width * 0.45
        and points[0][1] <= height * 0.20
        and points[1][0] >= width * 0.55
        and points[1][1] <= height * 0.20
        and points[2][0] >= width * 0.55
        and points[2][1] >= height * 0.80
        and points[3][0] <= width * 0.45
        and points[3][1] >= height * 0.80
    )


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

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    adaptive = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        51,
        7,
    )
    _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    image_area = width * height
    candidates: list[tuple[float, np.ndarray]] = []
    for thresholded in (otsu, adaptive):
        contours, _ = cv2.findContours(thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:12]:
            area = float(cv2.contourArea(contour))
            if not image_area * 0.08 <= area <= image_area * 0.98:
                continue
            perimeter = cv2.arcLength(contour, True)
            polygon = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue
            ordered = _order_points(polygon.reshape(4, 2).astype(np.float32))
            aspect_error = abs(_quadrilateral_aspect(ordered) - target_aspect) / target_aspect
            if aspect_error <= 0.35 and _has_consistent_edges(ordered):
                candidates.append((area * (1.0 - aspect_error), ordered))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]

    # A scanner may produce a page that exactly fills the image.  This is a
    # fallback only after contour detection, otherwise a similarly-proportioned
    # camera frame would be mistaken for the page and perspective would remain.
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
    if is_healthy_template(template):
        return read_healthy_answers(gray, template)
    answers = _read_answers_from_gray(gray, template)
    if template.get("templateCode") == "KR_SURVEY_V1":
        corrected = _read_answers_from_gray(gray, template, _kizilay_right_column_curve_shifts())
        if _analysis_score((warped, template, corrected, 0, 0)) > _analysis_score((warped, template, answers, 0, 0)):
            return corrected
    return answers


def _read_answers_robust(warped: np.ndarray, template: dict[str, Any]) -> list[AnswerResult]:
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    if is_healthy_template(template):
        candidates = [read_healthy_answers(variant, template) for variant in _gray_reading_variants(gray)]
        return max(candidates, key=_answers_quality_score)
    answers = _read_best_from_gray_variants(gray, template, use_local_search=True)
    if template.get("templateCode") == "KR_SURVEY_V1":
        corrected = _read_best_from_gray_variants(
            gray,
            template,
            shifts=_kizilay_right_column_curve_shifts(),
            use_local_search=True,
        )
        if _analysis_score((warped, template, corrected, 0, 0)) > _analysis_score((warped, template, answers, 0, 0)):
            return corrected
    return answers


def _read_best_from_gray_variants(
    gray: np.ndarray,
    template: dict[str, Any],
    shifts: dict[int, tuple[int, int]] | None = None,
    use_local_search: bool = False,
) -> list[AnswerResult]:
    candidates = [
        _read_answers_from_gray(variant, template, shifts=shifts, use_local_search=use_local_search)
        for variant in _gray_reading_variants(gray)
    ]
    return max(candidates, key=_answers_quality_score)


def _answers_quality_score(answers: list[AnswerResult]) -> tuple[int, int, float, int]:
    ok_count = sum(1 for answer in answers if answer.status in OK_STATUSES)
    review_required_count = sum(1 for answer in answers if answer.status in REVIEW_STATUSES)
    blank_count = sum(1 for answer in answers if answer.status == "BLANK")
    return (ok_count, -review_required_count, _form_confidence(answers), -blank_count)


def _gray_reading_variants(gray: np.ndarray) -> list[np.ndarray]:
    variants = [gray]

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    variants.append(clahe.apply(gray))

    normalized = _normalize_illumination(gray)
    variants.append(normalized)
    variants.append(clahe.apply(normalized))

    unique: list[np.ndarray] = []
    for variant in variants:
        if not any(np.array_equal(variant, existing) for existing in unique):
            unique.append(variant)
    return unique


def _normalize_illumination(gray: np.ndarray) -> np.ndarray:
    short_side = min(gray.shape[:2])
    kernel_size = max(31, int(short_side * 0.035))
    if kernel_size % 2 == 0:
        kernel_size += 1
    background = cv2.GaussianBlur(gray, (kernel_size, kernel_size), 0)
    normalized = cv2.divide(gray, background, scale=245)
    return cv2.normalize(normalized, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def _read_answers_from_gray(
    gray: np.ndarray,
    template: dict[str, Any],
    shifts: dict[int, tuple[int, int]] | None = None,
    use_local_search: bool = False,
) -> list[AnswerResult]:
    answers: list[AnswerResult] = []
    for question in template["questions"]:
        question_no = int(question["questionNo"])
        dx, dy = shifts.get(question_no, (0, 0)) if shifts else (0, 0)
        boxes = {option: _shift_box(box, dx, dy) for option, box in question["options"].items() if option in OPTION_ORDER}
        densities = {option: _mark_density(gray, box) for option, box in boxes.items()}
        first_decision = _decide_question(question_no, densities)
        if use_local_search and (first_decision.status in {"BLANK", "UNCERTAIN"} or first_decision.confidence < 0.78):
            densities = {option: _best_mark_density(gray, box, densities[option]) for option, box in boxes.items()}
        answers.append(_decide_question(question_no, densities))
    return answers


def _kizilay_right_column_curve_shifts() -> dict[int, tuple[int, int]]:
    return {
        14: (-130, 180),
        15: (-130, 170),
        16: (-125, 145),
        17: (-120, 115),
        18: (-110, 95),
        19: (-100, 75),
        20: (-70, 55),
        21: (-40, 35),
        22: (-25, 20),
        23: (-15, 10),
        24: (-5, 5),
        25: (0, 0),
    }


def _shift_box(box: dict[str, int], dx: int, dy: int) -> dict[str, int]:
    if dx == 0 and dy == 0:
        return box
    return {
        "x": int(box["x"]) + dx,
        "y": int(box["y"]) + dy,
        "width": int(box["width"]),
        "height": int(box["height"]),
    }


def _best_mark_density(gray: np.ndarray, box: dict[str, int], baseline: float) -> float:
    width = int(box["width"])
    height = int(box["height"])
    step = max(10, min(width, height) // 6)
    offsets = [0, -step, step]
    best = baseline
    for dy in offsets:
        for dx in offsets:
            best = max(best, _mark_density(gray, _shift_box(box, dx, dy)))
    return best


def _mark_density(gray: np.ndarray, box: dict[str, int]) -> float:
    x, y, width, height = int(box["x"]), int(box["y"]), int(box["width"]), int(box["height"])
    y1 = max(0, y)
    x1 = max(0, x)
    y2 = min(gray.shape[0], y + height)
    x2 = min(gray.shape[1], x + width)
    roi = gray[y1:y2, x1:x2]
    if roi.size == 0:
        return 0.0
    height, width = roi.shape[:2]

    yy, xx = np.ogrid[:height, :width]
    distance = (xx - width / 2) ** 2 + (yy - height / 2) ** 2
    center_radius = min(width, height) * 0.36
    background_inner_radius = min(width, height) * 0.42
    background_outer_radius = min(width, height) * 0.5
    center = roi[distance <= center_radius**2]
    background = roi[(distance >= background_inner_radius**2) & (distance <= background_outer_radius**2)]
    if center.size == 0 or background.size == 0:
        return 0.0

    background_darkness = float(np.median((255.0 - background.astype(np.float32)) / 255.0))
    darkness = (255.0 - center.astype(np.float32)) / 255.0
    normalized = np.clip((darkness - background_darkness) / max(1.0 - background_darkness, 0.01), 0, 1)
    dark_pixel_ratio = float(np.mean(normalized > 0.10))
    # A child may use a tick, a short slash or a small scribble instead of
    # filling the whole bubble.  Their total ink coverage is low, but the ink
    # still forms one meaningful stroke.  Reward that connected stroke while
    # leaving isolated paper/compression noise almost unchanged.
    ink_mask = (normalized > 0.16).astype(np.uint8)
    component_count, _, component_stats, _ = cv2.connectedComponentsWithStats(ink_mask, connectivity=8)
    largest_component_ratio = 0.0
    if component_count > 1:
        largest_component_ratio = float(np.max(component_stats[1:, cv2.CC_STAT_AREA])) / float(center.size)
    stroke_evidence = min(1.0, float(np.sqrt(largest_component_ratio / 0.12)))
    darkest_pixels = np.sort(normalized.reshape(-1))[int(normalized.size * 0.8) :]
    darkest_mean = float(np.mean(darkest_pixels)) if darkest_pixels.size else 0.0

    center_float = center.astype(np.float32)
    background_float = background.astype(np.float32)
    local_delta = max(0.0, (float(np.median(background_float)) - float(np.percentile(center_float, 35))) / 255.0)
    threshold = max(12.0, float(np.median(background_float)) - 22.0)
    locally_dark_ratio = float(np.mean(center_float < threshold))

    score = dark_pixel_ratio * 0.36 + darkest_mean * 0.29 + local_delta * 0.12 + locally_dark_ratio * 0.08 + stroke_evidence * 0.15
    return round(float(np.clip(score, 0, 1)), 4)


def _decide_question(question_no: int, densities: dict[str, float]) -> AnswerResult:
    ranked = sorted(densities.items(), key=lambda item: item[1], reverse=True)
    top_option, top_density = ranked[0]
    second_density = ranked[1][1]
    margin = top_density - second_density
    marked = [option for option, density in ranked if density >= DOUBLE_MARK_THRESHOLD]

    if len(marked) >= 2:
        return AnswerResult(questionNo=question_no, value=None, confidence=_double_confidence(ranked), source="UNRESOLVED", status="DOUBLE_MARK")

    if top_density < EMPTY_THRESHOLD and (top_density < LOW_CONTRAST_MARK_THRESHOLD or margin < UNCERTAIN_MARGIN):
        confidence = min(1.0, 1.0 - top_density / max(EMPTY_THRESHOLD, 0.01))
        return AnswerResult(questionNo=question_no, value="BLANK", confidence=round(confidence, 3), source="AUTO", status="BLANK")

    if top_density < MARK_THRESHOLD and margin >= UNCERTAIN_MARGIN and top_density >= LOW_CONTRAST_MARK_THRESHOLD:
        confidence = min(0.82, 0.58 + margin * 1.2)
        return AnswerResult(questionNo=question_no, value=top_option, confidence=round(confidence, 3), source="AUTO", status="OK")

    if top_density < MARK_THRESHOLD or margin < UNCERTAIN_MARGIN:
        confidence = min(0.69, max(0.35, top_density))
        return AnswerResult(questionNo=question_no, value=None, confidence=round(confidence, 3), source="UNRESOLVED", status="UNCERTAIN")

    confidence = min(1.0, 0.72 + (top_density - MARK_THRESHOLD) * 0.45 + margin * 0.35)
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
        if answer.status in {"DOUBLE_MARK", "MULTIPLE"}:
            penalty = 0.35
        elif answer.status in {"UNCERTAIN", "INVALID", "AMBIGUOUS"}:
            penalty = 0.5
        elif answer.status == "BLANK":
            penalty = 0.9
        score += answer.confidence * penalty
    return round(max(0.0, min(1.0, score / len(answers))), 3)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)

