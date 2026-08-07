from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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

