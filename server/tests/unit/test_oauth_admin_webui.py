"""Admin-webui OAuth allowlist (PR-4)."""

from __future__ import annotations

import pytest

from core.oauth_admin_webui import allowed_admin_oauth_origins, is_allowed_admin_oauth_next


def test_is_allowed_admin_oauth_next(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_ADMIN_WEBUI_ORIGINS", "http://localhost:3003,https://admin.example.com")
    assert is_allowed_admin_oauth_next("http://localhost:3003/") is True
    assert is_allowed_admin_oauth_next("https://admin.example.com") is True
    assert is_allowed_admin_oauth_next("http://evil.test") is False
    assert is_allowed_admin_oauth_next(None) is False


def test_allowed_origins_empty_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VT_ADMIN_WEBUI_ORIGIN", raising=False)
    monkeypatch.delenv("VT_ADMIN_WEBUI_ORIGINS", raising=False)
    assert allowed_admin_oauth_origins() == frozenset()
