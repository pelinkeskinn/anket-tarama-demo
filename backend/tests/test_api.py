from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_invalid_upload_error_model() -> None:
    response = client.post(
        "/api/omr/analyze",
        data={"clientRequestId": "test"},
        files={"image": ("bad.txt", b"bad", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_FILE"

