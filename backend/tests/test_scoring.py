from __future__ import annotations

import json
from pathlib import Path

from app.scoring import CURRENT_SURVEY_SCORE_MAP, SCORE_MAP, answer_score, is_review_cell


def test_score_map_is_likert_1_to_4() -> None:
    assert SCORE_MAP == {"NEVER": 1.0, "SOMETIMES": 2.0, "OFTEN": 3.0, "ALWAYS": 4.0}
    assert CURRENT_SURVEY_SCORE_MAP == {"NEVER": 1.0, "SOMETIMES": 2.0, "ALWAYS": 3.0}


def test_current_three_choice_survey_scores_always_as_three() -> None:
    assert answer_score("ALWAYS", template_code="HEALTHY_NUTRITION_V3") == 3.0


def test_blank_and_uncertain_are_not_scored() -> None:
    assert answer_score("BLANK", "BLANK") is None
    assert answer_score(None, "UNCERTAIN") is None
    assert is_review_cell(None, "AMBIGUOUS") is True
    assert is_review_cell("BLANK", "BLANK") is False
    assert is_review_cell("ALWAYS", "OK") is False


def test_expected_sample_forms_map_to_numeric_scores() -> None:
    path = Path(__file__).resolve().parents[2] / "sample-forms" / "expected-results.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    first = next(iter(payload.values()))
    scores = [answer_score(value) for value in first.values()]
    assert 1.0 in scores
    assert 4.0 in scores
    assert all(score in {1.0, 2.0, 3.0, 4.0} for score in scores)
