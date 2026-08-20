from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.config import MAX_UPLOAD_BYTES
from app.errors import OmrError, http_error
from app.models import AnalyzeResponse
from app.omr import analyze_image_bytes


router = APIRouter(prefix="/api/omr", tags=["omr"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    image: UploadFile = File(...),
    clientRequestId: str = Form(...),
    templateHint: str | None = Form(default=None),
    guidedCapture: bool = Form(default=False),
) -> AnalyzeResponse:
    if not clientRequestId.strip() or len(clientRequestId) > 64:
        raise http_error("UPLOAD_FAILED")
    if image.content_type and not (image.content_type.startswith("image/") or image.content_type == "application/pdf"):
        raise http_error("INVALID_FILE")

    data = await image.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise http_error("INVALID_FILE", status_code=413)

    try:
        return await run_in_threadpool(analyze_image_bytes, data, templateHint, guidedCapture)
    except OmrError as exc:
        raise http_error(exc.code) from exc
    except Exception as exc:
        raise http_error("PROCESSING_FAILED", status_code=500) from exc
