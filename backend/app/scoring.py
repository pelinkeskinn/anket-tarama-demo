from __future__ import annotations

# Historical four-choice Likert scoring.
SCORE_MAP: dict[str, float] = {
    "NEVER": 1.0,
    "SOMETIMES": 2.0,
    "OFTEN": 3.0,
    "ALWAYS": 4.0,
}

# The current Kızılay form has three response choices, not four.
CURRENT_SURVEY_SCORE_MAP: dict[str, float] = {
    "NEVER": 1.0,
    "SOMETIMES": 2.0,
    "ALWAYS": 3.0,
}

FREQUENCY_QUESTION_START = 12


def answer_score(value: str | None, status: str | None = None, template_code: str | None = None) -> float | None:
    score_map = CURRENT_SURVEY_SCORE_MAP if template_code == "HEALTHY_NUTRITION_V3" else SCORE_MAP
    if value in score_map:
        return score_map[value]
    return None


def is_review_cell(value: str | None, status: str | None = None) -> bool:
    if value in SCORE_MAP or value == "BLANK":
        return False
    if value is None:
        return True
    return status in UNCERTAIN_STATUSES
