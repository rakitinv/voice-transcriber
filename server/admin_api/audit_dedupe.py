"""Deduplicate high-frequency Admin API read audits (Redis SET NX)."""

from __future__ import annotations

import redis

from core.config import app_config
from core.logging import logger


def _redis() -> redis.Redis | None:
    try:
        return redis.Redis.from_url(app_config.redis.url, socket_connect_timeout=1.5)
    except Exception:
        logger.warning("admin read audit dedupe: redis connect failed", exc_info=True)
        return None


def admin_read_audit_dedupe_key(admin_user_id: str, action: str, detail_fp: str) -> str:
    fp = detail_fp[:200] if detail_fp else ""
    return f"vt:admin:read_audit:{admin_user_id}:{action}:{fp}"


def should_emit_admin_read_audit(
    *,
    admin_user_id: str,
    action: str,
    detail_fingerprint: str = "",
    ttl_seconds: int = 120,
) -> bool:
    """
    Return True if a new admin read audit row should be written (not a duplicate within TTL).

    If Redis is unavailable, returns True (emit every time — completeness over dedupe).
    """
    r = _redis()
    if r is None:
        return True
    key = admin_read_audit_dedupe_key(admin_user_id, action, detail_fingerprint)
    try:
        return bool(r.set(key, "1", nx=True, ex=int(ttl_seconds)))
    except redis.RedisError:
        logger.warning("admin read audit dedupe: redis command failed", exc_info=True)
        return True
    finally:
        try:
            r.close()
        except Exception:
            pass
