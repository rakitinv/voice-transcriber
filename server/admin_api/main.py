"""
Voice Transcriber Admin / Ops API (docs/ADMIN_OPS_CONSOLE.md).

Run: ``python -m uvicorn admin_api.main:app --host 0.0.0.0 --port 8000``
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from admin_api.routers import v1 as v1_routes
from core.config import app_config
from core.logging import logger


def _admin_cors_allow_origins() -> list[str]:
    raw = (os.environ.get("VT_ADMIN_CORS_ORIGINS") or "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    admin_ui = (
        os.environ.get("VT_ADMIN_WEBUI_ORIGIN") or "http://localhost:3003"
    ).strip().rstrip("/")
    defaults = [
        admin_ui,
        "http://localhost:3003",
        "http://127.0.0.1:3003",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for o in defaults:
        if not o or o in seen:
            continue
        seen.add(o)
        out.append(o)
    return out


def create_app() -> FastAPI:
    app = FastAPI(
        title="Voice Transcriber Admin API",
        version="0.1.0",
        description="Операционная админ-консоль (baseline)",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_admin_cors_allow_origins(),
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(v1_routes.router)

    @app.on_event("startup")
    async def startup_event():
        logger.info(
            "Starting Voice Transcriber Admin API (environment: %s)",
            app_config.environment,
        )

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("Shutting down Voice Transcriber Admin API")

    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "admin-api"}

    return app


app = create_app()
