"""Unit tests for deployment vs configuration compatibility checks."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.deployment_compat import (
    QueueConsumerSlice,
    collect_compatibility_issues,
    deploy_profile,
)


def test_gigaam_on_cpu_profile_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_DEPLOY_PROFILE", "cpu")
    with patch("core.deployment_compat.app_config") as cfg:
        cfg.asr.realtime_provider = "whisper"
        cfg.asr.final_provider = "gigaam"
        cfg.asr.default_provider = "whisper"
        cfg.asr.providers = {}
        cfg.diarization.enabled = False
        issues = collect_compatibility_issues(
            celery_queues=[QueueConsumerSlice("asr_final", True)],
        )
    assert any(i.code == "gigaam_requires_gpu_stack" and i.severity == "error" for i in issues)


def test_whisper_on_cpu_profile_no_gigaam_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_DEPLOY_PROFILE", "cpu")
    with patch("core.deployment_compat.app_config") as cfg:
        cfg.asr.realtime_provider = "whisper"
        cfg.asr.final_provider = "whisper"
        cfg.asr.default_provider = "whisper"
        cfg.asr.providers = {}
        cfg.diarization.enabled = False
        issues = collect_compatibility_issues(
            celery_queues=[QueueConsumerSlice("asr_final", True)],
        )
    assert not any(i.code == "gigaam_requires_gpu_stack" for i in issues)


def test_diarization_enabled_without_consumer_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_DEPLOY_PROFILE", "cpu")
    with patch("core.deployment_compat.app_config") as cfg:
        cfg.asr.realtime_provider = "whisper"
        cfg.asr.final_provider = "whisper"
        cfg.asr.default_provider = "whisper"
        cfg.asr.providers = {}
        cfg.diarization.enabled = True
        issues = collect_compatibility_issues(
            celery_queues=[
                QueueConsumerSlice("asr_final", True),
                QueueConsumerSlice("diarization", False),
            ],
        )
    assert any(i.code == "diarization_no_consumer" for i in issues)


def test_deploy_profile_defaults_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VT_DEPLOY_PROFILE", raising=False)
    assert deploy_profile() == "cpu"
