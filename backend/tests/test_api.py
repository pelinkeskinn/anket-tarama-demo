from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.models import AnalyzeResponse, ProcessingStats


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]


def test_readiness_checks_database() -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_render_origin_is_allowed() -> None:
    response = client.get("/healthz", headers={"Origin": "https://demo.onrender.com"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://demo.onrender.com"


def test_invalid_upload_error_model() -> None:
    response = client.post(
        "/api/omr/analyze",
        data={"clientRequestId": "test"},
        files={"image": ("bad.txt", b"bad", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_FILE"


def test_camera_template_hint_is_forwarded(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import app.api.omr as omr_api

    received: dict[str, str | None] = {}

    def fake_analyze(
        _data: bytes,
        template_hint: str | None = None,
        guided_capture: bool = False,
    ) -> AnalyzeResponse:
        received["templateHint"] = template_hint
        received["guidedCapture"] = str(guided_capture)
        return AnalyzeResponse(
            analysisId="test-hint",
            templateCode="HEALTHY_NUTRITION_V2",
            status="OK",
            formConfidence=1,
            blankCount=0,
            reviewRequiredCount=0,
            answers=[],
            processing=ProcessingStats(totalMs=1, perspectiveMs=0, omrMs=1),
        )

    monkeypatch.setattr(omr_api, "analyze_image_bytes", fake_analyze)
    response = client.post(
        "/api/omr/analyze",
        data={"clientRequestId": "camera-test", "templateHint": "HEALTHY_NUTRITION", "guidedCapture": "true"},
        files={"image": ("camera.jpg", b"jpeg", "image/jpeg")},
    )

    assert response.status_code == 200
    assert received["templateHint"] == "HEALTHY_NUTRITION"
    assert received["guidedCapture"] == "True"

