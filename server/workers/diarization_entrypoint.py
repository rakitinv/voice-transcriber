from __future__ import annotations

import os
import subprocess
import sys

from core.logging import logger


def main() -> int:
    os.environ.setdefault("VT_CELERY_ENABLE_DIARIZATION", "1")

    # Optional startup warmup/self-check: catches offline cache issues early.
    if os.environ.get("VT_DIARIZATION_WARMUP", "").strip().lower() in ("1", "true", "yes"):
        logger.info("VT_DIARIZATION_WARMUP enabled: running model warmup")
        rc = subprocess.call([sys.executable, "-m", "app.diarization.warmup"])
        if rc != 0:
            logger.error("Diarization warmup failed (exit_code=%s); refusing to start worker", rc)
            return rc

    cmd = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "workers.celery_app.celery_app",
        "worker",
        "--loglevel=info",
        "--queues=diarization",
    ]
    os.execvp(cmd[0], cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

