"""ASR tier resolution (realtime vs final)."""

from __future__ import annotations

from core.asr_tier import resolve_asr_provider_name, resolve_asr_recognition_model
from core.config import ASRConfig


def _asr_cfg(
    *,
    default: str = "whisper",
    realtime: str | None = None,
    final: str | None = None,
    recognition_model: str | None = "medium",
    realtime_model: str | None = None,
    final_model: str | None = None,
) -> ASRConfig:
    return ASRConfig(
        default_provider=default,
        realtime_provider=realtime,
        final_provider=final,
        recognition_model=recognition_model,
        realtime_recognition_model=realtime_model,
        final_recognition_model=final_model,
        providers={},
    )


def test_resolve_provider_falls_back_to_default() -> None:
    cfg = _asr_cfg(default="whisper", realtime=None, final=None)
    assert resolve_asr_provider_name(cfg, "realtime") == "whisper"
    assert resolve_asr_provider_name(cfg, "final") == "whisper"


def test_resolve_provider_tier_specific() -> None:
    cfg = _asr_cfg(
        default="whisper",
        realtime="faster_whisper",
        final="gigaam",
    )
    assert resolve_asr_provider_name(cfg, "realtime") == "faster_whisper"
    assert resolve_asr_provider_name(cfg, "final") == "gigaam"


def test_resolve_model_tier_override() -> None:
    cfg = _asr_cfg(
        default="whisper",
        realtime="faster_whisper",
        final="gigaam",
        realtime_model="small",
        final_model="v3_e2e_rnnt",
    )
    assert resolve_asr_recognition_model(cfg, "faster_whisper", "realtime") == "small"
    assert resolve_asr_recognition_model(cfg, "gigaam", "final") == "v3_e2e_rnnt"
    assert resolve_asr_recognition_model(cfg, "whisper", None) == "medium"


def test_resolve_model_legacy_recognition_model_only_for_default() -> None:
    cfg = _asr_cfg(default="whisper", recognition_model="large")
    assert resolve_asr_recognition_model(cfg, "whisper", "final") == "large"
    assert resolve_asr_recognition_model(cfg, "gigaam", "final") is None
