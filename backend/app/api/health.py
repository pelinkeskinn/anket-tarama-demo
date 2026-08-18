from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import SessionLocal


router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readiness() -> dict[str, str]:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail={"status": "not_ready"}) from exc
    return {"status": "ready"}
