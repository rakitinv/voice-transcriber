"""Conversation create realtime field resolution (R3)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

_mock_s3 = MagicMock()
_mock_s3.storage = MagicMock()
sys.modules.setdefault("core.s3", _mock_s3)

from app.api.conversations import _validate_client_realtime  # noqa: E402


def _patch_limits(monkeypatch, *, chunk_ms_max: int = 3000, media_chunk_ms_max: int = 2000) -> None:
    monkeypatch.setattr(
        "app.api.conversations.app_config.limits.chunk_ms_min",
        500,
        raising=False,
    )
    monkeypatch.setattr(
        "app.api.conversations.app_config.limits.chunk_ms_max",
        chunk_ms_max,
        raising=False,
    )
    monkeypatch.setattr(
        "app.api.conversations.app_config.limits.media_chunk_ms_max",
        media_chunk_ms_max,
        raising=False,
    )
    monkeypatch.setattr(
        "app.api.conversations.app_config.limits.allowed_realtime_modes",
        ("chunk", "windowed"),
        raising=False,
    )


def test_validate_asr_step_separate_from_legacy_chunk(monkeypatch):
    _patch_limits(monkeypatch)

    mode, asr = _validate_client_realtime(
        "windowed",
        None,
        asr_step_ms=2500,
        media_chunk_ms=1000,
    )
    assert mode == "windowed"
    assert asr == 2500


def test_legacy_chunk_ms_used_when_step_omitted(monkeypatch):
    _patch_limits(monkeypatch)

    _, asr = _validate_client_realtime("chunk", 1500)
    assert asr == 1500


def test_media_chunk_out_of_range_rejected(monkeypatch):
    _patch_limits(monkeypatch)

    with pytest.raises(HTTPException):
        _validate_client_realtime(None, None, media_chunk_ms=2500)


def test_asr_step_above_chunk_max_rejected(monkeypatch):
    _patch_limits(monkeypatch)

    with pytest.raises(HTTPException):
        _validate_client_realtime(None, None, asr_step_ms=3500)
