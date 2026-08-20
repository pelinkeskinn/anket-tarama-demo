from __future__ import annotations

import os

from fastapi import Header, HTTPException, Query


def require_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    token: str | None = Query(default=None),
) -> None:
    expected = os.getenv("ADMIN_TOKEN", "").strip()
    if not expected:
        return
    provided = (x_admin_token or token or "").strip()
    if provided != expected:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "UNAUTHORIZED", "message": "Yönetici yetkisi gerekli."}},
        )
