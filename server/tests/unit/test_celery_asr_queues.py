"""Celery ASR queue routing (parallel slice queue env override)."""

from __future__ import annotations

import os

import pytest

from workers.celery_app import asr_slice_queue


def test_asr_slice_queue_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VT_ASR_SLICE_QUEUE", raising=False)
    assert asr_slice_queue() == "asr_fast"


def test_asr_slice_queue_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_ASR_SLICE_QUEUE", "asr_final")
    assert asr_slice_queue() == "asr_final"
