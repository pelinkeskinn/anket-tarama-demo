from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class StoredForm(Base):
    __tablename__ = "demo_forms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    template_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    form_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    blank_count: Mapped[int] = mapped_column(Integer, nullable=False)
    manual_count: Mapped[int] = mapped_column(Integer, nullable=False)
    answers: Mapped[list[dict[str, object]]] = mapped_column("answers_json", JSON, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    possible_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    normalized_answers: Mapped[list["FormAnswer"]] = relationship(back_populates="form")


class FormAnswer(Base):
    __tablename__ = "form_answers"
    __table_args__ = (UniqueConstraint("form_id", "question_no", name="uq_form_answers_form_question"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("demo_forms.id"), nullable=False, index=True)
    question_no: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[str | None] = mapped_column(String(32), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    form: Mapped[StoredForm] = relationship(back_populates="normalized_answers")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    form_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    analysis_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
