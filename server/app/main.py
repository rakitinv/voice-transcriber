"""
Entry point for the FastAPI application.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import routes as api_routes
from .models import Base
from core.config import app_config
from core.db import engine
from core.logging import logger


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Voice Transcriber API",
        version="0.1.0",
        description="Production-grade speech transcription system",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, specify allowed origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routers
    app.include_router(api_routes.api_router)

    @app.on_event("startup")
    async def startup_event():
        """Initialize application on startup."""
        logger.info(f"Starting Voice Transcriber API (environment: {app_config.environment})")
        Base.metadata.create_all(bind=engine)
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

    return app


app = create_app()

