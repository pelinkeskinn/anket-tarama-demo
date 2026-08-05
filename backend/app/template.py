from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.config import TEMPLATE_PATH
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
    return [load_template(), _kizilay_survey_v1_template()]


def _option_box(center_x: int, center_y: int, size: int = 112) -> dict[str, int]:
    return {
        "x": center_x - size // 2,
        "y": center_y - size // 2,
        "width": size,
        "height": size,
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

