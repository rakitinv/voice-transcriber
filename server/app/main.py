"""
Entry point for the FastAPI application.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect

from .api import routes as api_routes
from .api import websocket as ws_routes
from .models import Base
from core.config import app_config
from core.db import engine
from core.logging import logger
from core.metrics import PrometheusMiddleware, metrics_response


def _cors_allow_origins() -> list[str]:
    """
    Origins allowed for credentialed browser requests (axios withCredentials: true).

    Browsers reject Access-Control-Allow-Origin: * together with credentials, so we
    must echo a concrete Origin (or match allow_origin_regex below).
    """
    raw = (os.environ.get("VT_CORS_ORIGINS") or "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    webui = (os.environ.get("VT_WEBUI_ORIGIN") or "http://localhost:3002").strip().rstrip("/")
    admin_ui = (os.environ.get("VT_ADMIN_WEBUI_ORIGIN") or "").strip().rstrip("/")
    defaults = [
        webui,
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3003",
        "http://127.0.0.1:3003",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]
    if admin_ui:
        defaults = [admin_ui, *defaults]
    out: list[str] = []
    seen: set[str] = set()
    for o in defaults:
        if not o or o in seen:
            continue
        seen.add(o)
        out.append(o)
    return out


def _verify_conversations_schema() -> None:
    """Fail fast with a clear message if Alembic migrations lag behind the ORM."""
    try:
        insp = inspect(engine)
        if not insp.has_table("conversations"):
            return
        cols = {c["name"] for c in insp.get_columns("conversations")}
        if "audio_uploaded_at" in cols:
            return
        msg = (
            "Database schema is missing column conversations.audio_uploaded_at. "
            "Apply migrations, e.g. from repo `docker/`: "
            "`docker compose run --rm migrate` or `alembic upgrade head`."
        )
        logger.critical(msg)
        raise RuntimeError(msg)
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning("Could not verify conversations table schema: %s", e)


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Voice Transcriber API",
        version="0.1.0",
        description="Production-grade speech transcription system",
    )

    # CORS: WebUI uses axios withCredentials + Bearer; browsers disallow * with credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allow_origins(),
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^(chrome-extension|moz-extension)://.+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(PrometheusMiddleware)

    # REST под /api; WebSocket под /ws (см. docs/WEBSOCKET.md)
    app.include_router(api_routes.api_router)
    app.include_router(ws_routes.router)

    @app.on_event("startup")
    async def startup_event():
        """Initialize application on startup."""
        logger.info(f"Starting Voice Transcriber API (environment: {app_config.environment})")
        Base.metadata.create_all(bind=engine)
        _verify_conversations_schema()
        g = app_config.auth.google
        if not g.client_id or g.client_id == "CHANGE_ME":
            logger.warning(
                "Google OAuth client_id is missing or still CHANGE_ME — API reads configs/server.yaml "
                "from disk (save the file) or set VT_GOOGLE_CLIENT_ID, then restart."
            )
        y = app_config.auth.yandex
        if not y.client_id or y.client_id == "CHANGE_ME":
            logger.warning(
                "Yandex OAuth client_id is missing or still CHANGE_ME — save configs/server.yaml "
                "or set VT_YANDEX_CLIENT_ID, then restart."
            )

    @app.on_event("shutdown")
    async def shutdown_event():
        """Cleanup on shutdown."""
        logger.info("Shutting down Voice Transcriber API")

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "environment": app_config.environment}

    @app.get("/metrics")
    async def prometheus_metrics():
        """Prometheus scrape endpoint (ТЗ §16)."""
        return metrics_response()

    return app


app = create_app()

