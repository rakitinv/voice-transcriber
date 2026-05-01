"""
Celery application factory.

Queues:
- asr_fast: короткие задачи нарезки параллельного ASR (ТЗ §17.7; transcribe_slice)
- asr_final: полный файл и merge после chord (transcribe_file, finalize_parallel_transcript)
- asr: прочие/legacy ASR-маршруты без явного queue=
- diarization: Speaker diarization tasks
- llm: LLM summary generation tasks
- cleanup: TTL cleanup tasks
"""

from __future__ import annotations

import os

from celery import Celery

from core.config import app_config
from core.logging import logger


def create_celery() -> Celery:
    """Create and configure Celery application."""
    app = Celery("voice_transcriber")

    # Redis broker: visibility_timeout must exceed longest expected task duration when
    # task_acks_late=True, otherwise messages are redelivered (duplicate ASR jobs). ТЗ §17.11.
    broker_transport_options: dict = {}
    _vt = os.environ.get("VT_CELERY_VISIBILITY_TIMEOUT", "").strip()
    if _vt:
        try:
            broker_transport_options["visibility_timeout"] = int(_vt)
        except ValueError:
            pass

    # Celery configuration
    conf: dict = {
        "broker_url": app_config.redis.url,
        "result_backend": app_config.redis.url,
        "task_serializer": "json",
        "accept_content": ["json"],
        "result_serializer": "json",
        "timezone": "UTC",
        "enable_utc": True,
        "task_routes": {
            "workers.tasks.asr.transcribe_slice": {"queue": "asr_fast"},
            "workers.tasks.asr.finalize_parallel_transcript": {"queue": "asr_final"},
            "workers.tasks.asr.transcribe_file": {"queue": "asr_final"},
            "workers.tasks.asr.*": {"queue": "asr"},
            "workers.tasks.diarization.*": {"queue": "diarization"},
            "workers.tasks.llm.*": {"queue": "llm"},
            "workers.tasks.embeddings.*": {"queue": "llm"},
            "workers.tasks.cleanup.*": {"queue": "cleanup"},
        },
        "task_acks_late": True,
        "worker_prefetch_multiplier": 1,
    }
    if broker_transport_options:
        conf["broker_transport_options"] = broker_transport_options

    app.conf.update(**conf)

    logger.info("Celery application created")
    if broker_transport_options.get("visibility_timeout") is not None:
        logger.info(
            "Celery broker visibility_timeout=%s",
            broker_transport_options["visibility_timeout"],
        )

    return app


celery_app = create_celery()

# Явная регистрация задач: autodiscover_tasks(["workers"]) в этом layout не подхватывает
# workers/tasks/*.py (секция [tasks] в логе worker остаётся пустой).
from workers.tasks import asr, cleanup, embeddings, llm  # noqa: E402, F401

if os.environ.get("VT_CELERY_ENABLE_DIARIZATION", "").strip().lower() in ("1", "true", "yes"):
    from workers.tasks import diarization  # noqa: E402, F401

