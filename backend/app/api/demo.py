from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import SAMPLE_FORMS_DIR


router = APIRouter(prefix="/api/demo", tags=["demo"])

ALLOWED_SAMPLE_FORMS = frozenset(
    {
        "filled-clean.png",
        "filled-with-blanks.png",
        "filled-double-mark.png",
        "filled-faint-marks.png",
        "filled-erased-mark.png",
        "filled-perspective.png",
        "filled-shadow.png",
        "filled-blurry.png",
        "blank-form-v2.png",
        "filled-clean-v2.png",
        "filled-faint-v2.png",
    }
)


@router.get("/sample-forms/{filename}")
def sample_form(filename: str) -> FileResponse:
    path = (SAMPLE_FORMS_DIR / filename).resolve()
    if filename not in ALLOWED_SAMPLE_FORMS or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "Demo görsel bulunamadı."}},
        )
    return FileResponse(path)
