"""Redis-backed counters for failed credential attempts (refresh, API key)."""

from __future__ import annotations

import redis

from core.config import app_config
from core.logging import logger


def _redis() -> redis.Redis | None:
    try:
        return redis.Redis.from_url(app_config.redis.url, socket_connect_timeout=1.5)
    except Exception:
        logger.warning("auth lockout: redis connect failed", exc_info=True)
        return None


def is_refresh_blocked(ip: str | None) -> bool:
    if not ip or not app_config.auth.lockout.enabled:
        return False
    r = _redis()
    if r is None:
        return False
    try:
        key = f"vt:auth:refresh:block:{ip}"
        try:
            return bool(r.exists(key))
        except redis.RedisError:
            logger.warning("auth lockout: redis exists failed", exc_info=True)
            return False
    finally:
        try:
            r.close()
        except Exception:
            pass


def register_refresh_failure(ip: str | None) -> bool:
    """
    Increment failed refresh counter for ``ip``.

    Returns:
        True if the IP is now blocked (caller should return HTTP 429).
    """
    if not ip or not app_config.auth.lockout.enabled:
        return False
    cfg = app_config.auth.lockout
    r = _redis()
    if r is None:
        return False
    try:
        cnt_key = f"vt:auth:refresh:fail:{ip}"
        block_key = f"vt:auth:refresh:block:{ip}"
        try:
            n = int(r.incr(cnt_key))
            if n == 1:
                r.expire(cnt_key, int(cfg.window_seconds))
            if n >= int(cfg.refresh_invalid_max_per_ip):
                r.setex(block_key, int(cfg.block_seconds), "1")
                return True
            return False
        except redis.RedisError:
            logger.warning("auth lockout: redis incr failed", exc_info=True)
            return False
    finally:
        try:
            r.close()
        except Exception:
            pass


def clear_refresh_failures(ip: str | None) -> None:
    """Reset failure counter after a successful refresh (helps shared NAT)."""
    if not ip or not app_config.auth.lockout.enabled:
        return
    r = _redis()
    if r is None:
        return
    try:
        try:
            r.delete(f"vt:auth:refresh:fail:{ip}")
        except redis.RedisError:
            logger.warning("auth lockout: redis delete failed", exc_info=True)
    finally:
        try:
            r.close()
        except Exception:
            pass


def is_api_key_blocked(ip: str | None) -> bool:
    if not ip or not app_config.auth.lockout.enabled:
        return False
    r = _redis()
    if r is None:
        return False
    try:
        key = f"vt:auth:apikey:block:{ip}"
        try:
            return bool(r.exists(key))
        except redis.RedisError:
            logger.warning("auth lockout: redis exists failed", exc_info=True)
            return False
    finally:
        try:
            r.close()
        except Exception:
            pass


def register_api_key_failure(ip: str | None) -> bool:
    if not ip or not app_config.auth.lockout.enabled:
        return False
    cfg = app_config.auth.lockout
    r = _redis()
    if r is None:
        return False
    try:
        cnt_key = f"vt:auth:apikey:fail:{ip}"
        block_key = f"vt:auth:apikey:block:{ip}"
        try:
            n = int(r.incr(cnt_key))
            if n == 1:
                r.expire(cnt_key, int(cfg.window_seconds))
            if n >= int(cfg.api_key_invalid_max_per_ip):
                r.setex(block_key, int(cfg.block_seconds), "1")
                return True
            return False
        except redis.RedisError:
            logger.warning("auth lockout: redis incr failed", exc_info=True)
            return False
    finally:
        try:
            r.close()
        except Exception:
            pass
