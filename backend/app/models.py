from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


AnswerValue = Literal["NEVER", "SOMETIMES", "OFTEN", "ALWAYS", "BLANK"]
AnswerStatus = Literal[
    "OK",
    "BLANK",
    "DOUBLE_MARK",
    "UNCERTAIN",
    "MARKED",
    "MULTIPLE",
    "INVALID",
    "AMBIGUOUS",
]
AnswerSource = Literal["AUTO", "MANUAL", "UNRESOLVED"]


class AnswerResult(BaseModel):
    questionNo: int
    value: AnswerValue | None
    confidence: float = Field(ge=0, le=1)
    source: AnswerSource
    status: AnswerStatus
    manualCorrection: str | None = None
    section: int | None = Field(default=None, ge=1, le=2)
    selectedIndex: int | None = Field(default=None, ge=0, le=3)
    selectedLabel: str | None = None
    optionLabels: list[str] | None = Field(default=None, min_length=1, max_length=4)
    scores: list[float] | None = Field(default=None, min_length=4, max_length=4)


class ProcessingStats(BaseModel):
    totalMs: int
    perspectiveMs: int
    omrMs: int


class AnalyzeResponse(BaseModel):
    analysisId: str
    templateCode: str
    status: Literal["OK", "REVIEW_REQUIRED", "TOO_MANY_UNCERTAIN"]
    formConfidence: float = Field(ge=0, le=1)
    blankCount: int
    reviewRequiredCount: int
    answers: list[AnswerResult]
    processing: ProcessingStats


class StoredFormCreate(BaseModel):
    analysisId: str = Field(min_length=1, max_length=64)
    templateCode: str = Field(min_length=1, max_length=64)
    formConfidence: float = Field(ge=0, le=1)
    answers: list[AnswerResult] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_question_set(self) -> "StoredFormCreate":
        from app.template import expected_question_count

        question_numbers = [answer.questionNo for answer in self.answers]
        expected_count = expected_question_count(self.templateCode)
        count = expected_count if expected_count is not None else len(self.answers)
        expected_numbers = list(range(1, count + 1))
        if expected_count is not None and len(self.answers) != expected_count:
            raise ValueError(f"answers must contain each question number from 1 to {expected_count} exactly once")
        if sorted(question_numbers) != expected_numbers:
            raise ValueError("answers must contain consecutive question numbers starting at 1 exactly once")
        return self


class StoredFormSummary(BaseModel):
    id: int
    createdAt: datetime
    formConfidence: float
    blankCount: int
    manualCount: int
    possibleDuplicate: bool = False


class StoredFormPage(BaseModel):
    items: list[StoredFormSummary]
    total: int


class StoredFormDetail(StoredFormSummary):
    analysisId: str
    templateCode: str
    answers: list[AnswerResult]

