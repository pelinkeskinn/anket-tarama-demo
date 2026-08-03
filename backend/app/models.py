from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


AnswerValue = Literal["NEVER", "SOMETIMES", "ALWAYS", "BLANK"]
AnswerStatus = Literal["OK", "BLANK", "DOUBLE_MARK", "UNCERTAIN"]
AnswerSource = Literal["AUTO", "MANUAL", "UNRESOLVED"]


class AnswerResult(BaseModel):
    questionNo: int
    value: AnswerValue | None
    confidence: float = Field(ge=0, le=1)
    source: AnswerSource
    status: AnswerStatus
    manualCorrection: str | None = None


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
    analysisId: str
    templateCode: str
    formConfidence: float = Field(ge=0, le=1)
    answers: list[AnswerResult]


class StoredFormSummary(BaseModel):
    id: int
    createdAt: datetime
    formConfidence: float
    blankCount: int
    manualCount: int


class StoredFormDetail(StoredFormSummary):
    analysisId: str
    templateCode: str
    answers: list[AnswerResult]

