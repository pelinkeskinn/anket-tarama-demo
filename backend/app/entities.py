from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StoredForm(Base):
    __tablename__ = "demo_forms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    template_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    form_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    blank_count: Mapped[int] = mapped_column(Integer, nullable=False)
    manual_count: Mapped[int] = mapped_column(Integer, nullable=False)
    answers: Mapped[list[dict[str, object]]] = mapped_column("answers_json", JSON, nullable=False)
