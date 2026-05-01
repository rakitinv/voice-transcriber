"""VAD preference merge (env + optional user.preferences overrides)."""

from __future__ import annotations

import pytest

from app.asr.vad_prefs import vad_filter_and_params


@pytest.fixture(autouse=True)
def _vad_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_ASR_VAD_FILTER", "1")
    monkeypatch.setenv("VT_ASR_VAD_MIN_SILENCE_MS", "400")
    monkeypatch.setenv("VT_ASR_VAD_THRESHOLD", "0.5")
    monkeypatch.setenv("VT_ASR_VAD_SPEECH_PAD_MS", "100")


def test_vad_env_only() -> None:
    f, p = vad_filter_and_params(None)
    assert f is True
    assert p is not None
    assert p["min_silence_duration_ms"] == 400
    assert p["threshold"] == 0.5
    assert p["speech_pad_ms"] == 100


def test_vad_custom_overrides() -> None:
    prefs = {
        "asr_vad_use_custom": True,
        "asr_vad_filter": True,
        "asr_vad_min_silence_ms": 200,
        "asr_vad_threshold": 0.25,
        "asr_vad_speech_pad_ms": 500,
    }
    f, p = vad_filter_and_params(prefs)
    assert f is True
    assert p is not None
    assert p["min_silence_duration_ms"] == 200
    assert p["threshold"] == 0.25
    assert p["speech_pad_ms"] == 500


def test_vad_custom_threshold_none_drops_key() -> None:
    prefs = {
        "asr_vad_use_custom": True,
        "asr_vad_filter": True,
        "asr_vad_min_silence_ms": 200,
        "asr_vad_threshold": None,
        "asr_vad_speech_pad_ms": 500,
    }
    f, p = vad_filter_and_params(prefs)
    assert f is True
    assert p is not None
    assert "threshold" not in p


def test_vad_filter_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_ASR_VAD_FILTER", "0")
    f, p = vad_filter_and_params(None)
    assert f is False
    assert p is None
