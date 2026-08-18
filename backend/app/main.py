from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import re
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.demo import router as demo_router
from app.api.forms import router as forms_router
from app.api.health import router as health_router
from app.api.omr import router as omr_router
from app.config import get_settings
from app.database import init_db


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "Authorization", "X-Request-ID"],
    )

    @application.middleware("http")
    async def add_operational_headers(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request_id = supplied_request_id if REQUEST_ID_PATTERN.fullmatch(supplied_request_id) else uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(self)"
        return response

    application.include_router(health_router)
    application.include_router(omr_router)
    application.include_router(forms_router)
    application.include_router(demo_router)
    return application


app = create_app()
