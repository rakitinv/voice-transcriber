"""
Logging configuration for the application.

Logs are structured and include:
- API requests
- Worker jobs
- Auth events
- Storage operations
"""

import logging
import sys
from pathlib import Path

from .config import app_config

# Create logs directory if it doesn't exist
LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Configure root logger
logging.basicConfig(
    level=logging.DEBUG if app_config.environment == "development" else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "app.log"),
    ],
)

# Get logger for this module
logger = logging.getLogger(__name__)

# Set log levels for third-party libraries
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
