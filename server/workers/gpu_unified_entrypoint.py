from __future__ import annotations

import os
import subprocess
import sys

from core.logging import logger


def _queues() -> str:
    return os.environ.get(
        "VT_GPU_UNIFIED_WORKER_QUEUES",
        "asr_fast,asr_final,diarization",
    ).strip()


def _concurrency_args() -> list[str]:
    raw = os.environ.get("VT_GPU_UNIFIED_CONCURRENCY", "").strip()
    if not raw:
        return []
    return ["--concurrency", raw]


def main() -> int:
    os.environ.setdefault("VT_CELERY_ENABLE_DIARIZATION", "1")

    if os.environ.get("VT_DIARIZATION_WARMUP", "").strip().lower() in ("1", "true", "yes"):
        logger.info("VT_DIARIZATION_WARMUP enabled: running model warmup")
        rc = subprocess.call([sys.executable, "-m", "app.diarization.warmup"])
        if rc != 0:
            logger.error("Diarization warmup failed (exit_code=%s); refusing to start worker", rc)
            return rc

    queues = _queues()
    if not queues:
        logger.error("VT_GPU_UNIFIED_WORKER_QUEUES is empty")
        return 1

    cmd = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "workers.celery_app.celery_app",
        "worker",
        "--loglevel=info",
        "--queues",
        queues,
        *_concurrency_args(),
    ]
    logger.info("Starting unified GPU worker: queues=%s", queues)
    os.execvp(cmd[0], cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
