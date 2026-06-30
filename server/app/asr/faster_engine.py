"""
Общий inference через faster-whisper (движки `whisper` и `faster_whisper` в конфиге).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from faster_whisper import WhisperModel

from plugins.asr_base import ASRSegment

from .vad_prefs import vad_filter_and_params

_model_cache: dict[tuple[str, str, str, str], WhisperModel] = {}
_model_lock = threading.Lock()


def _model_size(config: Dict[str, Any]) -> str:
    return str(config.get("model") or "base")


def _realtime_device() -> str:
    """Realtime (API/WebSocket) device; separate from batch final ASR on GPU workers."""
    raw = (os.environ.get("VT_ASR_REALTIME_DEVICE") or os.environ.get("VT_ASR_DEVICE") or "cpu").strip()
    return raw.lower() or "cpu"


def _realtime_compute_type() -> str:
    raw = (
        os.environ.get("VT_ASR_REALTIME_COMPUTE_TYPE")
        or os.environ.get("VT_ASR_COMPUTE_TYPE")
        or "int8"
    ).strip()
    return raw or "int8"


def get_whisper_model(config: Dict[str, Any]) -> WhisperModel:
    """Один экземпляр на (model_size, device, compute_type)."""
    size = _model_size(config)
    device = _realtime_device()
    compute_type = _realtime_compute_type()
    key = (size, device, compute_type)
    with _model_lock:
        if key not in _model_cache:
            _model_cache[key] = WhisperModel(
                size,
                device=device,
                compute_type=compute_type,
            )
        return _model_cache[key]


def transcribe_file_to_segments(
    audio_path: str,
    config: Dict[str, Any],
    language: Optional[str] = None,
    *,
    vad_preferences: Optional[dict] = None,
) -> List[ASRSegment]:
    model = get_whisper_model(config)
    vad_filter, vad_params = vad_filter_and_params(vad_preferences)

    # Optional quality controls (kept env-driven for easy tuning in docker-compose).
    # When unset, faster-whisper defaults are used.
    temperature_raw = os.environ.get("VT_ASR_TEMPERATURE")
    temperature = float(temperature_raw) if temperature_raw not in (None, "") else None

    patience_raw = os.environ.get("VT_ASR_PATIENCE")
    patience = float(patience_raw) if patience_raw not in (None, "") else None

    cond_prev_raw = os.environ.get("VT_ASR_CONDITION_ON_PREVIOUS_TEXT")
    condition_on_previous_text: bool | None = None
    if cond_prev_raw not in (None, ""):
        condition_on_previous_text = cond_prev_raw.strip().lower() not in ("0", "false", "no")

    initial_prompt = os.environ.get("VT_ASR_INITIAL_PROMPT")
    if initial_prompt is not None:
        initial_prompt = initial_prompt.strip()
        if not initial_prompt:
            initial_prompt = None

    hotwords = os.environ.get("VT_ASR_HOTWORDS")
    if hotwords is not None:
        hotwords = hotwords.strip()
        if not hotwords:
            hotwords = None

    # Thresholds (advanced): pass only when set
    def _f(name: str) -> float | None:
        raw = os.environ.get(name)
        return float(raw) if raw not in (None, "") else None

    compression_ratio_threshold = _f("VT_ASR_COMPRESSION_RATIO_THRESHOLD")
    log_prob_threshold = _f("VT_ASR_LOG_PROB_THRESHOLD")
    no_speech_threshold = _f("VT_ASR_NO_SPEECH_THRESHOLD")

    kwargs: Dict[str, Any] = {
        "language": language,
        "beam_size": int(os.environ.get("VT_ASR_BEAM_SIZE", "5")),
        "vad_filter": vad_filter,
        "vad_parameters": vad_params if vad_filter else None,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if patience is not None:
        kwargs["patience"] = patience
    if condition_on_previous_text is not None:
        kwargs["condition_on_previous_text"] = condition_on_previous_text
    if initial_prompt is not None:
        kwargs["initial_prompt"] = initial_prompt
    if hotwords is not None:
        # faster-whisper supports hotword biasing in recent versions.
        # If the installed version doesn't, we'll retry without it (see below).
        kwargs["hotwords"] = hotwords
    if compression_ratio_threshold is not None:
        kwargs["compression_ratio_threshold"] = compression_ratio_threshold
    if log_prob_threshold is not None:
        kwargs["log_prob_threshold"] = log_prob_threshold
    if no_speech_threshold is not None:
        kwargs["no_speech_threshold"] = no_speech_threshold

    try:
        segments_gen, _info = model.transcribe(audio_path, **kwargs)
    except TypeError as e:
        # Backward compatibility: older faster-whisper may not accept some kwargs (e.g. hotwords).
        if "hotwords" in kwargs and "hotwords" in str(e):
            kwargs.pop("hotwords", None)
            segments_gen, _info = model.transcribe(audio_path, **kwargs)
        else:
            raise
    out: List[ASRSegment] = []
    for s in segments_gen:
        text = (s.text or "").strip()
        if text:
            out.append(ASRSegment(start=float(s.start), end=float(s.end), text=text))
    if not out:
        return [ASRSegment(start=0.0, end=0.5, text="")]
    return out


def transcribe_bytes_to_text(
    audio_data: bytes,
    config: Dict[str, Any],
    language: Optional[str] = None,
    suffix: str = ".webm",
    *,
    vad_preferences: Optional[dict] = None,
) -> str:
    from .audio_util import bytes_to_tempfile, media_to_wav_16k_mono

    raw = bytes_to_tempfile(audio_data, suffix=suffix)
    wav: Path | None = None
    try:
        wav = media_to_wav_16k_mono(raw)
        segs = transcribe_file_to_segments(
            str(wav), config, language=language, vad_preferences=vad_preferences
        )
        return " ".join(s.text for s in segs).strip() or ""
    finally:
        raw.unlink(missing_ok=True)
        if wav is not None:
            wav.unlink(missing_ok=True)
