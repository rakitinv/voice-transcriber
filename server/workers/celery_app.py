"""
Celery application factory.

Queues:
- asr: ASR transcription tasks
- diarization: Speaker diarization tasks
- llm: LLM summary generation tasks
- cleanup: TTL cleanup tasks
"""

from __future__ import annotations

from celery import Celery

from core.config import app_config
from core.logging import logger


def create_celery() -> Celery:
    """Create and configure Celery application."""
    app = Celery("voice_transcriber")

    # Celery configuration
    app.conf.update(
        broker_url=app_config.redis.url,
        result_backend=app_config.redis.url,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_routes={
            "workers.tasks.asr.*": {"queue": "asr"},
            "workers.tasks.diarization.*": {"queue": "diarization"},
            "workers.tasks.llm.*": {"queue": "llm"},
            "workers.tasks.cleanup.*": {"queue": "cleanup"},
        },
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )

    # Auto-discover tasks
    app.autodiscover_tasks(["workers.tasks"])

    logger.info("Celery application created")
    return app


celery_app = create_celery()

