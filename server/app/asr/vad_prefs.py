"""
Параметры VAD (faster-whisper / Silero) из env и опциональных пользовательских настроек.

Ключи в `user.preferences` (см. `/api/settings/user`):
- asr_vad_use_custom: bool — если true, ниже перекрывают env для соответствующих полей
- asr_vad_filter: bool
- asr_vad_min_silence_ms: int
- asr_vad_threshold: float | null — null = не передавать в faster-whisper (его дефолт Silero)
- asr_vad_speech_pad_ms: int | null — null = не передавать
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def _env_bool(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no")


@dataclass(frozen=True)
class AsrVadEnvDefaults:
    vad_filter: bool
    min_silence_ms: int
    threshold: float | None
    speech_pad_ms: int | None


def read_asr_vad_env_defaults() -> AsrVadEnvDefaults:
    """Текущие значения из окружения процесса (docker-compose / хост)."""
    vad_filter = _env_bool("VT_ASR_VAD_FILTER", "1")
    min_ms = int(os.environ.get("VT_ASR_VAD_MIN_SILENCE_MS", "500"))
    th_raw = os.environ.get("VT_ASR_VAD_THRESHOLD")
    threshold = float(th_raw) if th_raw not in (None, "") else None
    pad_raw = os.environ.get("VT_ASR_VAD_SPEECH_PAD_MS")
    speech_pad = int(pad_raw) if pad_raw not in (None, "") else None
    return AsrVadEnvDefaults(
        vad_filter=vad_filter,
        min_silence_ms=min_ms,
        threshold=threshold,
        speech_pad_ms=speech_pad,
    )


def vad_filter_and_params(preferences: dict | None) -> tuple[bool, dict[str, Any] | None]:
    """
    Вернуть (vad_filter, vad_parameters) для faster-whisper `model.transcribe(...)`.
    """
    env = read_asr_vad_env_defaults()
    vad_filter = env.vad_filter
    params: dict[str, Any] = {"min_silence_duration_ms": env.min_silence_ms}
    if env.threshold is not None:
        params["threshold"] = float(env.threshold)
    if env.speech_pad_ms is not None:
        params["speech_pad_ms"] = int(env.speech_pad_ms)

    prefs = preferences if isinstance(preferences, dict) else {}
    if prefs.get("asr_vad_use_custom") is True:
        if "asr_vad_filter" in prefs and prefs["asr_vad_filter"] is not None:
            vad_filter = bool(prefs["asr_vad_filter"])
        if "asr_vad_min_silence_ms" in prefs and prefs["asr_vad_min_silence_ms"] is not None:
            params["min_silence_duration_ms"] = int(prefs["asr_vad_min_silence_ms"])
        if "asr_vad_threshold" in prefs:
            if prefs["asr_vad_threshold"] is None:
                params.pop("threshold", None)
            else:
                params["threshold"] = float(prefs["asr_vad_threshold"])
        if "asr_vad_speech_pad_ms" in prefs:
            if prefs["asr_vad_speech_pad_ms"] is None:
                params.pop("speech_pad_ms", None)
            else:
                params["speech_pad_ms"] = int(prefs["asr_vad_speech_pad_ms"])

    if not vad_filter:
        return False, None
    return True, params
