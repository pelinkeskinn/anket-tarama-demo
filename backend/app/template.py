from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.config import HEALTHY_NUTRITION_TEMPLATE_PATH, HEALTHY_NUTRITION_TEMPLATE_V2_PATH, TEMPLATE_PATH
from app.errors import OmrError


@lru_cache
def load_template() -> dict[str, Any]:
    try:
        with TEMPLATE_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise OmrError("INVALID_TEMPLATE") from exc


@lru_cache
def load_templates() -> list[dict[str, Any]]:
    return [*_healthy_nutrition_reference_templates(), _omr_survey_v2_template(), load_template(), _kizilay_survey_v1_template()]


def _option_box(center_x: int, center_y: int, size: int = 112) -> dict[str, int]:
    return {
        "x": center_x - size // 2,
        "y": center_y - size // 2,
        "width": size,
        "height": size,
    }


def _v2_option_box(center_x: int, center_y: int, size: int = 130) -> dict[str, int]:
    return {
        "x": center_x - size // 2,
        "y": center_y - size // 2,
        "width": size,
        "height": size,
    }


@lru_cache
def _healthy_nutrition_reference_templates() -> tuple[dict[str, Any], ...]:
    """Load one-time calibrations extracted from the canonical PDF revisions."""
    return tuple(_load_healthy_nutrition_reference(path) for path in (HEALTHY_NUTRITION_TEMPLATE_V2_PATH, HEALTHY_NUTRITION_TEMPLATE_PATH))


def _load_healthy_nutrition_reference(path: Any) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            calibration = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise OmrError("INVALID_TEMPLATE") from exc

    page_width = int(calibration["pageWidth"])
    page_height = int(calibration["pageHeight"])
    questions = []
    for question in calibration["questions"]:
        options = {}
        optionLabels = {}
        for option, circle in question["options"].items():
            center_x = round(float(circle["cx"]) * page_width)
            center_y = round(float(circle["cy"]) * page_height)
            radius = float(circle["r"]) * page_width
            roi_size = max(1, round(radius * 2.55))
            options[option] = _option_box(center_x, center_y, size=roi_size)
            optionLabels[option] = str(circle["label"])
        questions.append(
            {
                "questionNo": int(question["questionNo"]),
                "section": int(question["section"]),
                "options": options,
                "optionLabels": optionLabels,
            }
        )

    return {
        **calibration,
        "markerMargin": 0,
        "questionCount": len(questions),
        "questions": questions,
    }


def _question(question_no: int, centers: tuple[tuple[int, int], tuple[int, int], tuple[int, int]]) -> dict[str, Any]:
    return {
        "questionNo": question_no,
        "options": {
            "NEVER": _option_box(*centers[0]),
            "SOMETIMES": _option_box(*centers[1]),
            "ALWAYS": _option_box(*centers[2]),
        },
    }


def _omr_survey_v2_template() -> dict[str, Any]:
    option_offsets = {"NEVER": 390, "SOMETIMES": 640, "ALWAYS": 890}
    left_x = 220
    right_x = 1300
    start_y = 840
    row_gap = 152

    questions = []
    for question_no in range(1, 26):
        if question_no <= 13:
            column_x = left_x
            row = question_no - 1
        else:
            column_x = right_x
            row = question_no - 14
        y = start_y + row * row_gap
        questions.append(
            {
                "questionNo": question_no,
                "options": {
                    option: _v2_option_box(column_x + offset, y)
                    for option, offset in option_offsets.items()
                },
            }
        )

    return {
        "templateCode": "OMR_SURVEY_V2",
        "pageWidth": 2480,
        "pageHeight": 3508,
        "markerMargin": 120,
        "markerSize": 180,
        "markerType": "ARUCO_4X4_50",
        "markerIds": {
            "topLeft": 10,
            "topRight": 11,
            "bottomRight": 12,
            "bottomLeft": 13,
        },
        "questionCount": 25,
        "questions": questions,
    }


def _kizilay_survey_v1_template() -> dict[str, Any]:
    left_rows = [
        ((867, 825), (999, 824), (1131, 825)),
        ((865, 1007), (995, 1011), (1132, 1011)),
        ((868, 1190), (1000, 1193), (1133, 1197)),
        ((867, 1377), (1001, 1381), (1132, 1379)),
        ((869, 1561), (1003, 1562), (1132, 1562)),
        ((871, 1743), (1001, 1744), (1133, 1742)),
        ((871, 1927), (1004, 1928), (1133, 1927)),
        ((871, 2108), (1001, 2108), (1135, 2105)),
        ((869, 2295), (1001, 2291), (1132, 2294)),
        ((869, 2475), (1001, 2476), (1133, 2477)),
        ((871, 2659), (1001, 2662), (1133, 2660)),
        ((869, 2841), (1001, 2842), (1135, 2841)),
        ((871, 3023), (999, 3026), (1135, 3022)),
    ]
    right_rows = [
        ((1901, 824), (2035, 825), (2167, 826)),
        ((1901, 1009), (2035, 1009), (2167, 1009)),
        ((1899, 1193), (2033, 1193), (2168, 1192)),
        ((1901, 1378), (2033, 1377), (2165, 1378)),
        ((1898, 1563), (2032, 1562), (2171, 1562)),
        ((1897, 1744), (2033, 1744), (2169, 1745)),
        ((1900, 1927), (2032, 1928), (2170, 1929)),
        ((1899, 2110), (2031, 2110), (2169, 2111)),
        ((1900, 2294), (2033, 2296), (2168, 2297)),
        ((1900, 2477), (2032, 2479), (2165, 2481)),
        ((1901, 2660), (2032, 2660), (2167, 2663)),
        ((1900, 2842), (2031, 2843), (2163, 2848)),
    ]
    questions = [
        *[_question(index + 1, centers) for index, centers in enumerate(left_rows)],
        *[_question(index + 14, centers) for index, centers in enumerate(right_rows)],
    ]
    return {
        "templateCode": "KR_SURVEY_V1",
        "pageWidth": 2480,
        "pageHeight": 3508,
        "markerMargin": 140,
        "markerSize": 130,
        "questionCount": 25,
        "questions": questions,
    }

