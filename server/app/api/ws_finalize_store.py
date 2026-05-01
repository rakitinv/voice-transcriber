"""
Идемпотентность finalize_id для канала /ws/audio (ТЗ §17).

При отсутствии VT_REDIS_URL дедупликация между процессами API недоступна — каждая
finalize считается «первой» (приемлемо для dev с одним инстансом).
"""

from __future__ import annotations

import logging
import os
from typing import Final

logger = logging.getLogger(__name__)

_KEY_PREFIX: Final[str] = "vt:ws:finalize:"
_TTL_DONE_S = 7 * 24 * 3600
_TTL_PENDING_S = 30 * 60  # keep short: allows client retry after errors


def try_claim_finalize_pending(conversation_id: str, finalize_id: str) -> str:
    """
    Try to claim (conversation_id, finalize_id) for processing.

    Returns:
      - "claimed": key created with value "pending"
      - "duplicate": key already exists (pending or done)
      - "no_redis": dedup unavailable (treat as claimed)

    Redis: SET key NX EX (pending ttl). On Redis error, log and return "no_redis".
    """
    redis_url = (os.environ.get("VT_REDIS_URL") or "").strip()
    if not redis_url:
        logger.debug("finalize idempotency: VT_REDIS_URL unset — no cross-process dedup")
        return "no_redis"
    try:
        import redis as redis_sync

        r = redis_sync.Redis.from_url(redis_url)
        key = f"{_KEY_PREFIX}{conversation_id}:{finalize_id}"
        ok = r.set(key, "pending", nx=True, ex=_TTL_PENDING_S)
        return "claimed" if ok else "duplicate"
    except Exception as e:
        logger.warning("finalize Redis claim failed: %s — accepting as first claim", e)
        return "no_redis"


def mark_finalize_done(conversation_id: str, finalize_id: str) -> None:
    """Mark claimed finalize_id as done (best-effort)."""
    redis_url = (os.environ.get("VT_REDIS_URL") or "").strip()
    if not redis_url:
        return
    try:
        import redis as redis_sync

        r = redis_sync.Redis.from_url(redis_url)
        key = f"{_KEY_PREFIX}{conversation_id}:{finalize_id}"
        # Prefer overwriting to "done" and extending TTL.
        r.set(key, "done", ex=_TTL_DONE_S)
    except Exception as e:
        logger.warning("finalize Redis mark_done failed: %s", e)


def release_finalize_pending(conversation_id: str, finalize_id: str) -> None:
    """
    Release a pending claim so the client can retry with the same finalize_id.

    Best-effort; only deletes when Redis is configured.
    """
    redis_url = (os.environ.get("VT_REDIS_URL") or "").strip()
    if not redis_url:
        return
    try:
        import redis as redis_sync

        r = redis_sync.Redis.from_url(redis_url)
        key = f"{_KEY_PREFIX}{conversation_id}:{finalize_id}"
        # Delete regardless of value; pending TTL is short anyway.
        r.delete(key)
    except Exception as e:
        logger.warning("finalize Redis release failed: %s", e)
