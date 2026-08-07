from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.database import create_form, delete_form, get_form, init_db, list_forms
from app.errors import OmrError, http_error
from app.models import AnalyzeResponse, StoredFormCreate, StoredFormDetail, StoredFormSummary
from app.omr import analyze_image_bytes
from app.config import MAX_UPLOAD_BYTES, SAMPLE_FORMS_DIR


app = FastAPI(title="Kizilay Demo OMR Prototype")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|\d{1,3}(\.\d{1,3}){3}|[A-Za-z0-9-]+\.onrender\.com|[A-Za-z0-9-]+\.vercel\.app)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/omr/analyze", response_model=AnalyzeResponse)
async def analyze(image: UploadFile = File(...), clientRequestId: str = Form(...)) -> AnalyzeResponse:
    if not clientRequestId.strip():
        raise http_error("UPLOAD_FAILED")
    if image.content_type and not image.content_type.startswith("image/"):
        raise http_error("INVALID_FILE")

    data = await image.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise http_error("INVALID_FILE", status_code=413)

    try:
        return analyze_image_bytes(data)
    except OmrError as exc:
        raise http_error(exc.code) from exc
    except Exception as exc:
        raise http_error("PROCESSING_FAILED", status_code=500) from exc


@app.post("/api/demo/forms", response_model=StoredFormDetail)
def save_form(payload: StoredFormCreate) -> StoredFormDetail:
    return create_form(payload)


@app.get("/api/demo/forms", response_model=list[StoredFormSummary])
def forms() -> list[StoredFormSummary]:
    return list_forms()


@app.get("/api/demo/forms/{formId}", response_model=StoredFormDetail)
def form_detail(formId: int) -> StoredFormDetail:
    form = get_form(formId)
    if form is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Kayıt bulunamadı."}})
    return form


@app.delete("/api/demo/forms/{formId}")
def remove_form(formId: int) -> dict[str, bool]:
    deleted = delete_form(formId)
    if not deleted:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Kayıt bulunamadı."}})
    return {"deleted": True}


@app.get("/api/demo/sample-forms/{filename}")
def sample_form(filename: str) -> FileResponse:
    allowed = {
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
    if filename not in allowed:
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Demo görsel bulunamadı."}})
    path = (SAMPLE_FORMS_DIR / filename).resolve()
    if not path.exists() or not Path(path).is_file():
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Demo görsel bulunamadı."}})
    return FileResponse(path)

