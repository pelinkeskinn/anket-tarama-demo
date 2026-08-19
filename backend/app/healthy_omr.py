from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.models import AnswerResult


TEMPLATE_CODE_PREFIX = "HEALTHY_NUTRITION_V"
OPTION_ORDER = ("NEVER", "SOMETIMES", "OFTEN", "ALWAYS")
MARK_SCORE_THRESHOLD = 0.65
AMBIGUOUS_SCORE_THRESHOLD = 0.38
MIN_INK_RATIO = 0.055
CLEAR_HAND_MARK_SCORE = 0.14
CLEAR_HAND_MARK_MARGIN = 0.06


@dataclass(frozen=True)
class FillFeatures:
    score: float
    inner_dark_ratio: float
    center_dark_ratio: float
    quadrant_coverage: tuple[float, float, float, float]
    connected_component_ratio: float
    local_contrast: float

    @property
    def is_filled(self) -> bool:
        return bool(
            self.score >= MARK_SCORE_THRESHOLD
            and self.inner_dark_ratio >= 0.68
            and self.center_dark_ratio >= 0.65
            and min(self.quadrant_coverage) >= 0.58
            and self.connected_component_ratio >= 0.65
        )

    @property
    def has_ink(self) -> bool:
        return bool(
            self.inner_dark_ratio >= MIN_INK_RATIO
            or self.connected_component_ratio >= 0.035
            or self.score >= 0.14
        )


def is_healthy_template(template: dict[str, Any]) -> bool:
    return str(template.get("templateCode", "")).startswith(TEMPLATE_CODE_PREFIX)


def read_answers(gray: np.ndarray, template: dict[str, Any]) -> list[AnswerResult]:
    answers: list[AnswerResult] = []
    for question in template["questions"]:
        features = [calculate_fill_features(gray, question["options"][option]) for option in OPTION_ORDER]
        answers.append(evaluate_question(question, features))
    return answers


def calculate_fill_features(gray: np.ndarray, box: dict[str, int]) -> FillFeatures:
    x, y = int(box["x"]), int(box["y"])
    width, height = int(box["width"]), int(box["height"])
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(gray.shape[1], x + width), min(gray.shape[0], y + height)
    roi = gray[y1:y2, x1:x2]
    if roi.size == 0:
        return FillFeatures(0.0, 0.0, 0.0, (0.0, 0.0, 0.0, 0.0), 0.0, 0.0)

    roi = cv2.GaussianBlur(roi, (3, 3), 0).astype(np.float32)
    roi_height, roi_width = roi.shape
    yy, xx = np.ogrid[:roi_height, :roi_width]
    cx, cy = (roi_width - 1) / 2.0, (roi_height - 1) / 2.0
    radius = min(roi_width, roi_height) * 0.392
    distance = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    inner_mask = distance <= radius * 0.68
    center_mask = distance <= radius * 0.34
    background_mask = (distance >= radius * 1.08) & (distance <= radius * 1.25)
    if not np.any(background_mask):
        background_mask = distance >= radius * 1.05

    background_level = float(np.median(roi[background_mask])) if np.any(background_mask) else 255.0
    darkness = np.clip((background_level - roi) / max(background_level, 40.0), 0.0, 1.0)
    ink = darkness >= 0.13
    inner_ink = ink & inner_mask

    inner_dark_ratio = _masked_ratio(ink, inner_mask)
    center_dark_ratio = _masked_ratio(ink, center_mask)
    quadrants = (
        inner_mask & (xx < cx) & (yy < cy),
        inner_mask & (xx >= cx) & (yy < cy),
        inner_mask & (xx < cx) & (yy >= cy),
        inner_mask & (xx >= cx) & (yy >= cy),
    )
    quadrant_coverage = tuple(_masked_ratio(ink, mask) for mask in quadrants)

    component_mask = inner_ink.astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(component_mask, connectivity=8)
    largest_component = float(np.max(stats[1:, cv2.CC_STAT_AREA])) if count > 1 else 0.0
    connected_component_ratio = largest_component / max(float(np.count_nonzero(inner_mask)), 1.0)

    center_values = darkness[inner_mask]
    local_contrast = float(np.percentile(center_values, 65)) if center_values.size else 0.0
    balanced_coverage = min(quadrant_coverage)
    score = (
        inner_dark_ratio * 0.32
        + center_dark_ratio * 0.18
        + balanced_coverage * 0.22
        + connected_component_ratio * 0.15
        + local_contrast * 0.13
    )
    return FillFeatures(
        score=round(float(np.clip(score, 0.0, 1.0)), 4),
        inner_dark_ratio=round(inner_dark_ratio, 4),
        center_dark_ratio=round(center_dark_ratio, 4),
        quadrant_coverage=tuple(round(value, 4) for value in quadrant_coverage),
        connected_component_ratio=round(connected_component_ratio, 4),
        local_contrast=round(local_contrast, 4),
    )


def evaluate_question(question: dict[str, Any], features: list[FillFeatures]) -> AnswerResult:
    question_no = int(question["questionNo"])
    section = int(question["section"])
    scores = [feature.score for feature in features]
    filled = [index for index, feature in enumerate(features) if feature.is_filled]
    inked = [index for index, feature in enumerate(features) if feature.has_ink]
    hand_marked = [index for index, feature in enumerate(features) if _is_clear_hand_mark(feature)]
    strongest_index = int(np.argmax(scores))
    strongest = features[strongest_index]

    common = {
        "questionNo": question_no,
        "section": section,
        "scores": scores,
    }
    if len(filled) >= 2:
        confidence = min(0.99, 0.72 + min(scores[index] for index in filled) * 0.25)
        return AnswerResult(value=None, confidence=round(confidence, 3), source="UNRESOLVED", status="MULTIPLE", **common)

    if len(filled) == 1:
        selected_index = filled[0]
        competing_ink = [index for index in inked if index != selected_index and scores[index] >= AMBIGUOUS_SCORE_THRESHOLD]
        if competing_ink:
            return AnswerResult(value=None, confidence=0.5, source="UNRESOLVED", status="AMBIGUOUS", **common)
        option = OPTION_ORDER[selected_index]
        label = str(question["optionLabels"][option])
        runner_up = max(score for index, score in enumerate(scores) if index != selected_index)
        confidence = min(0.99, 0.70 + scores[selected_index] * 0.22 + max(0.0, scores[selected_index] - runner_up) * 0.12)
        return AnswerResult(
            value=option,
            confidence=round(confidence, 3),
            source="AUTO",
            status="MARKED",
            selectedIndex=selected_index,
            selectedLabel=label,
            **common,
        )

    # Respondents do not always fill a bubble completely. A single, clearly
    # dominant tick, cross, slash, dot or partial fill still expresses an
    # unambiguous choice and should not make the whole form fail review.
    if len(hand_marked) >= 2:
        confidence = min(0.99, 0.68 + min(scores[index] for index in hand_marked) * 0.25)
        return AnswerResult(value=None, confidence=round(confidence, 3), source="UNRESOLVED", status="MULTIPLE", **common)

    if len(hand_marked) == 1:
        selected_index = hand_marked[0]
        runner_up = max(score for index, score in enumerate(scores) if index != selected_index)
        margin = scores[selected_index] - runner_up
        if margin >= CLEAR_HAND_MARK_MARGIN:
            option = OPTION_ORDER[selected_index]
            label = str(question["optionLabels"][option])
            confidence = min(0.94, 0.70 + scores[selected_index] * 0.20 + margin * 0.20)
            return AnswerResult(
                value=option,
                confidence=round(confidence, 3),
                source="AUTO",
                status="MARKED",
                selectedIndex=selected_index,
                selectedLabel=label,
                **common,
            )

    if not inked:
        confidence = min(0.99, 0.85 + max(0.0, MIN_INK_RATIO - strongest.inner_dark_ratio))
        return AnswerResult(value="BLANK", confidence=round(confidence, 3), source="AUTO", status="BLANK", **common)

    if (
        strongest.score >= AMBIGUOUS_SCORE_THRESHOLD
        and strongest.inner_dark_ratio >= 0.62
        and min(strongest.quadrant_coverage) >= 0.45
        and strongest.connected_component_ratio >= 0.55
    ):
        confidence = max(0.35, min(0.69, 0.45 + abs(strongest.score - MARK_SCORE_THRESHOLD)))
        return AnswerResult(value=None, confidence=round(confidence, 3), source="UNRESOLVED", status="AMBIGUOUS", **common)

    confidence = min(0.95, 0.68 + max(strongest.inner_dark_ratio, strongest.connected_component_ratio) * 0.25)
    return AnswerResult(value=None, confidence=round(confidence, 3), source="UNRESOLVED", status="INVALID", **common)


def _is_clear_hand_mark(feature: FillFeatures) -> bool:
    """Accept deliberate marks while rejecting isolated scan speckles."""
    return bool(
        feature.is_filled
        or (
            feature.score >= CLEAR_HAND_MARK_SCORE
            and feature.inner_dark_ratio >= 0.10
            and feature.connected_component_ratio >= 0.10
            and (feature.center_dark_ratio >= 0.10 or max(feature.quadrant_coverage) >= 0.25)
        )
    )


def template_match_score(warped: np.ndarray, template: dict[str, Any]) -> float:
    """Validate the calibrated circle grid and section bands after alignment."""
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    circle_matches = 0
    total = 0
    for question in template["questions"]:
        for option in OPTION_ORDER:
            total += 1
            box = question["options"][option]
            features = calculate_fill_features(gray, box)
            # A correctly aligned empty circle has no inner ink; a correctly
            # aligned answer is a balanced fill.  A displaced printed border
            # cutting through the inner mask looks like an invalid stroke and
            # identifies the wrong form revision.
            inner_geometry_matches = not features.has_ink or features.is_filled
            if _has_printed_circle(gray, box) and inner_geometry_matches:
                circle_matches += 1
    circle_score = circle_matches / max(total, 1)

    red_score = 0.0
    hsv = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)
    for band in template.get("sectionBands", []):
        x, y = int(band["x"]), int(band["y"])
        width, height = int(band["width"]), int(band["height"])
        roi = hsv[max(0, y) : min(hsv.shape[0], y + height), max(0, x) : min(hsv.shape[1], x + width)]
        if roi.size:
            hue, saturation, value = cv2.split(roi)
            red = (((hue <= 12) | (hue >= 170)) & (saturation >= 80) & (value >= 45))
            red_score += min(1.0, float(np.mean(red)) / 0.55)
    red_score /= max(len(template.get("sectionBands", [])), 1)
    return round(circle_score * 0.82 + red_score * 0.18, 4)


def generate_debug_images(
    original: np.ndarray,
    warped: np.ndarray,
    marker_source: np.ndarray,
    template: dict[str, Any],
    answers: list[AnswerResult],
    analysis_id: str,
    debug_root: Path,
) -> Path:
    output_dir = debug_root / analysis_id
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_image(output_dir / "01_original.jpg", original)

    markers = original.copy()
    for index, point in enumerate(marker_source):
        center = tuple(np.round(point).astype(int))
        cv2.circle(markers, center, 16, (0, 255, 255), 4)
        cv2.putText(markers, str(index + 1), center, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 180, 255), 2)
    _write_image(output_dir / "03_markers_detected.jpg", markers)
    _write_image(output_dir / "04_perspective_corrected.jpg", warped)
    _write_image(output_dir / "05_template_aligned.jpg", warped)

    overlay = warped.copy()
    colors = {
        "MARKED": (40, 180, 40),
        "BLANK": (150, 150, 150),
        "MULTIPLE": (20, 20, 220),
        "AMBIGUOUS": (0, 210, 255),
        "INVALID": (0, 130, 255),
    }
    by_question = {answer.questionNo: answer for answer in answers}
    for question in template["questions"]:
        answer = by_question[int(question["questionNo"])]
        color = colors.get(answer.status, (255, 255, 255))
        for option_index, option in enumerate(OPTION_ORDER):
            box = question["options"][option]
            center = (int(box["x"]) + int(box["width"]) // 2, int(box["y"]) + int(box["height"]) // 2)
            radius = round(min(int(box["width"]), int(box["height"])) * 0.392)
            cv2.circle(overlay, center, radius, color, 2)
            score = answer.scores[option_index] if answer.scores else 0.0
            cv2.putText(
                overlay,
                f"Q{answer.questionNo:02d}-{option_index + 1} {score:.2f}",
                (center[0] - radius, center[1] - radius - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.28,
                color,
                1,
                cv2.LINE_AA,
            )
        first_box = question["options"][OPTION_ORDER[0]]
        cv2.putText(
            overlay,
            f"{answer.status} c={answer.confidence:.2f}",
            (int(first_box["x"]) - 115, int(first_box["y"]) + int(first_box["height"]) // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            color,
            1,
            cv2.LINE_AA,
        )
    _write_image(output_dir / "06_answer_rois.jpg", overlay)

    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    thresholded = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 9)
    _write_image(output_dir / "07_thresholded_rois.png", thresholded)
    _write_image(output_dir / "08_final_result.jpg", overlay)
    return output_dir


def _masked_ratio(values: np.ndarray, mask: np.ndarray) -> float:
    count = int(np.count_nonzero(mask))
    return float(np.count_nonzero(values & mask)) / max(count, 1)


def _write_image(path: Path, image: np.ndarray) -> None:
    success, encoded = cv2.imencode(path.suffix, image)
    if not success:
        raise OSError(f"Could not encode debug image: {path.name}")
    path.write_bytes(encoded.tobytes())


def _has_printed_circle(gray: np.ndarray, box: dict[str, int]) -> bool:
    x, y = int(box["x"]), int(box["y"])
    width, height = int(box["width"]), int(box["height"])
    roi = gray[max(0, y) : min(gray.shape[0], y + height), max(0, x) : min(gray.shape[1], x + width)]
    if roi.size == 0:
        return False
    roi_height, roi_width = roi.shape
    yy, xx = np.ogrid[:roi_height, :roi_width]
    cx, cy = (roi_width - 1) / 2.0, (roi_height - 1) / 2.0
    radius = min(roi_width, roi_height) * 0.392
    distance = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    ring = (distance >= radius * 0.84) & (distance <= radius * 1.15)
    outside = (distance >= radius * 1.12) & (distance <= radius * 1.25)
    background = float(np.median(roi[outside])) if np.any(outside) else 255.0
    ring_dark_ratio = float(np.mean(roi[ring] < background - 35.0)) if np.any(ring) else 0.0
    return ring_dark_ratio >= 0.08
