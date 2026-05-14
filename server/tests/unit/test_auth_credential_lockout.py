"""Sprint 6: Redis lockout helpers (Epic R)."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

from app.services import auth_credential_lockout as lockout
from core.config import app_config


def test_refresh_blocked_when_redis_flag_exists() -> None:
    fake = MagicMock()
    fake.exists.return_value = True
    with patch.object(lockout, "_redis", return_value=fake):
        assert lockout.is_refresh_blocked("203.0.113.1") is True
    fake.close.assert_called_once()


def test_register_refresh_failure_sets_block_at_threshold() -> None:
    cfg = replace(app_config.auth.lockout, enabled=True, refresh_invalid_max_per_ip=3)
    auth_cfg = replace(app_config.auth, lockout=cfg)
    mock_app = replace(app_config, auth=auth_cfg)
    fake = MagicMock()
    fake.incr.return_value = 3
    with patch.object(lockout, "app_config", mock_app):
        with patch.object(lockout, "_redis", return_value=fake):
            blocked = lockout.register_refresh_failure("198.51.100.2")
    assert blocked is True
    fake.setex.assert_called_once()


def test_clear_refresh_failures_deletes_key() -> None:
    fake = MagicMock()
    with patch.object(lockout, "_redis", return_value=fake):
        lockout.clear_refresh_failures("198.51.100.3")
    fake.delete.assert_called_once_with("vt:auth:refresh:fail:198.51.100.3")
