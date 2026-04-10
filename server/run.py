"""
Application entry point for running the FastAPI server.

Usage:
    python -m server.run
    or
    uvicorn server.run:app --host 0.0.0.0 --port 8000
"""

import uvicorn

from app.main import app
from core.config import app_config

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=app_config.host,
        port=app_config.port,
        reload=app_config.environment == "development",
        log_level="info",
    )
