from __future__ import annotations

# Likert scoring for Excel export and normalized answers.
# Confirmed by survey owner: no reverse items; NEVER=1 … ALWAYS=4.
SCORE_MAP: dict[str, float] = {
    "NEVER": 1.0,
    "SOMETIMES": 2.0,
    "OFTEN": 3.0,
    "ALWAYS": 4.0,
}

UNCERTAIN_STATUSES = frozenset({"UNCERTAIN", "INVALID", "MULTIPLE", "AMBIGUOUS", "DOUBLE_MARK"})


def answer_score(value: str | None, status: str | None = None) -> float | None:
    if value in SCORE_MAP:
        return SCORE_MAP[value]
    return None


def is_review_cell(value: str | None, status: str | None = None) -> bool:
    if value in SCORE_MAP or value == "BLANK":
        return False
    if value is None:
        return True
    return status in UNCERTAIN_STATUSES
