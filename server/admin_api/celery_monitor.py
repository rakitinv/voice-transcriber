"""
Celery named-queue visibility for Admin API (ADMIN_OPS_CONSOLE §5.1).

Queue names are canonical with ``server/workers/celery_app.py`` task_routes.
With Redis broker, list length per queue name approximates pending depth.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import redis

# Lazy-import celery_app inside get_queue_consumer_status_cached to avoid importing
# workers/tasks (and S3 client init) when only running lightweight admin unit tests.
CELERY_MONITORED_QUEUES: tuple[str, ...] = (
    "asr_fast",
    "asr_final",
    "asr",
    "diarization",
    "llm",
    "cleanup",
)

_CACHE_TTL_SEC = 10.0
_cache_at: float = 0.0
_cache_payload: dict[str, dict[str, object]] | None = None


def clear_queue_consumer_status_cache() -> None:
    """Test helper: reset Celery inspect cache."""
    global _cache_at, _cache_payload
    _cache_at = 0.0
    _cache_payload = None


@dataclass(frozen=True)
class QueueConsumerStatus:
    queue: str
    consumer_responding: bool
    queue_depth: int | None = None
    detail: str | None = None


def _queues_per_worker_from_inspect(active_queues: dict | None) -> dict[str, set[str]]:
    """worker_name -> set of queue names."""
    out: dict[str, set[str]] = {}
    if not isinstance(active_queues, dict):
        return out
    for worker_name, queues in active_queues.items():
        names: set[str] = set()
        if isinstance(queues, list):
            for q in queues:
                if isinstance(q, dict) and q.get("name"):
                    names.add(str(q["name"]))
        out[str(worker_name)] = names
    return out


def _redis_queue_depths() -> dict[str, int | None]:
    """Best-effort LLEN per queue name (Redis Celery broker)."""
    out: dict[str, int | None] = {q: None for q in CELERY_MONITORED_QUEUES}
    try:
        from core.config import app_config

        r = redis.Redis.from_url(app_config.redis.url, socket_connect_timeout=1.5)
        try:
            for qname in CELERY_MONITORED_QUEUES:
                try:
                    out[qname] = int(r.llen(qname))
                except Exception:
                    out[qname] = None
        finally:
            r.close()
    except Exception:
        pass
    return out


def get_queue_consumer_status_cached() -> list[QueueConsumerStatus]:
    """
    Return whether at least one worker reports each named queue in ``active_queues``,
    plus optional Redis list depth per queue.

    Result is cached briefly to avoid hammering the broker on each UI poll.
    """
    global _cache_at, _cache_payload
    now = time.monotonic()
    if _cache_payload is not None and (now - _cache_at) < _CACHE_TTL_SEC:
        payload = _cache_payload
    else:
        depths = _redis_queue_depths()
        raw: dict[str, dict[str, object]] = {}
        try:
            from workers.celery_app import celery_app

            insp = celery_app.control.inspect(timeout=1.0)
            aq = insp.active_queues() if insp else None
            per_worker = _queues_per_worker_from_inspect(aq)
            for qname in CELERY_MONITORED_QUEUES:
                ok = any(qname in qs for qs in per_worker.values()) if per_worker else False
                row_detail: str | None = (
                    None if per_worker else "no_workers_or_inspect_empty"
                )
                raw[qname] = {
                    "ok": ok,
                    "detail": row_detail,
                    "depth": depths.get(qname),
                }
        except Exception as e:
            err = str(e)[:300]
            for qname in CELERY_MONITORED_QUEUES:
                raw[qname] = {"ok": False, "detail": err, "depth": depths.get(qname)}
        _cache_payload = raw
        _cache_at = now
        payload = raw

    out_rows: list[QueueConsumerStatus] = []
    for qname in CELERY_MONITORED_QUEUES:
        cell = payload[qname] if payload else {}
        depth_val = cell.get("depth")
        depth: int | None = int(depth_val) if isinstance(depth_val, int) else None
        det = cell.get("detail")
        detail_str: str | None = str(det) if det is not None else None
        out_rows.append(
            QueueConsumerStatus(
                queue=qname,
                consumer_responding=bool(cell.get("ok")),
                queue_depth=depth,
                detail=detail_str,
            )
        )
    return out_rows
