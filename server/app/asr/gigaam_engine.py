"""
GigaAM inference (Russian ASR).

Short utterances: model.transcribe (<= ~25 s).
Long audio: transcribe_longform when enabled, else ffmpeg chunking.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logging import logger
from core.webm_pcm import ffmpeg_binary
from plugins.asr_base import ASRSegment

# GigaAM documents a 25 s limit for .transcribe(); stay slightly below.
_MAX_SHORT_SECONDS = 24.0

_model_cache: dict[tuple[str, str], Any] = {}
_model_lock = threading.Lock()


def _model_name(config: Dict[str, Any]) -> str:
    return str(config.get("model") or "v3_e2e_rnnt").strip()


def _device() -> str:
    dev = (os.environ.get("VT_ASR_DEVICE") or "cpu").strip().lower()
    return dev if dev in ("cpu", "cuda") else "cpu"


def _longform_enabled(config: Dict[str, Any]) -> bool:
    env = os.environ.get("VT_GIGAAM_LONGFORM")
    if env is not None and str(env).strip():
        return str(env).strip().lower() in ("1", "true", "yes", "on")
    if config.get("longform_enabled") is not None:
        return bool(config.get("longform_enabled"))
    return True


def _chunk_seconds() -> float:
    raw = os.environ.get("VT_GIGAAM_CHUNK_SECONDS", "20")
    try:
        v = float(raw)
        return max(5.0, min(v, _MAX_SHORT_SECONDS))
    except ValueError:
        return 20.0


def _apply_cache_env(config: Dict[str, Any]) -> None:
    cache_dir = (config.get("model_cache_dir") or "").strip()
    if cache_dir:
        os.environ.setdefault("HF_HOME", cache_dir)
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", cache_dir)
        os.environ.setdefault("TRANSFORMERS_CACHE", cache_dir)


def _apply_hf_token(config: Dict[str, Any]) -> None:
    token_env = (config.get("hf_token_env") or "VT_HF_TOKEN").strip()
    token = os.environ.get(token_env, "").strip() if token_env else ""
    if not token:
        return
    os.environ.setdefault("HF_TOKEN", token)
    os.environ.setdefault("HUGGINGFACE_HUB_TOKEN", token)


def _warn_non_russian(language: Optional[str]) -> None:
    if not language or not str(language).strip():
        return
    lang = str(language).strip().lower().split("-")[0]
    if lang != "ru":
        logger.warning(
            "GigaAM is optimized for Russian; language=%r may yield poor results",
            language,
        )


def get_gigaam_model(config: Dict[str, Any]) -> Any:
    """Load and cache GigaAM model (lazy import)."""
    _apply_cache_env(config)
    name = _model_name(config)
    device = _device()
    key = (name, device)
    with _model_lock:
        if key in _model_cache:
            return _model_cache[key]
        try:
            import gigaam  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "gigaam package is not installed (poetry install --with gigaam)"
            ) from e
        try:
            import torch  # type: ignore
        except ImportError as e:
            raise RuntimeError("torch is not installed (required for GigaAM)") from e

        if device == "cuda" and not torch.cuda.is_available():
            logger.warning("VT_ASR_DEVICE=cuda but CUDA unavailable; using CPU")
            device = "cpu"
            key = (name, device)

        model = gigaam.load_model(name)
        if device == "cuda" and hasattr(model, "to"):
            try:
                model.to("cuda")
            except Exception as e:
                logger.warning("GigaAM .to(cuda) failed (%s); keeping CPU", e)
        _model_cache[key] = model
        return model


def _wav_duration_seconds(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wf:
        rate = wf.getframerate()
        frames = wf.getnframes()
    return float(frames) / float(rate) if rate else 0.0


def _slice_wav(src: Path, start_s: float, end_s: float) -> Path:
    exe = ffmpeg_binary()
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH (set VT_FFMPEG_PATH)")
    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    out = Path(out_path)
    try:
        subprocess.run(
            [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{max(0.0, float(start_s)):.3f}",
                "-to",
                f"{max(0.0, float(end_s)):.3f}",
                "-i",
                str(src),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                str(out),
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
    except Exception:
        out.unlink(missing_ok=True)
        raise
    return out


def _text_from_transcribe_result(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text.strip()
    return str(result).strip()


def _segments_from_longform(result: Any) -> List[ASRSegment]:
    out: List[ASRSegment] = []
    if result is None:
        return out
    for item in result:
        text = (getattr(item, "text", None) or "").strip()
        if not text:
            continue
        out.append(
            ASRSegment(
                start=float(getattr(item, "start", 0.0) or 0.0),
                end=float(getattr(item, "end", 0.0) or 0.0),
                text=text,
            )
        )
    return out


def _transcribe_short_wav(model: Any, wav_path: Path) -> List[ASRSegment]:
    dur = _wav_duration_seconds(wav_path)
    text = _text_from_transcribe_result(model.transcribe(str(wav_path)))
    if not text:
        return [ASRSegment(start=0.0, end=max(dur, 0.1), text="")]
    return [ASRSegment(start=0.0, end=max(dur, 0.1), text=text)]


def _transcribe_longform_wav(model: Any, wav_path: Path, config: Dict[str, Any]) -> List[ASRSegment]:
    _apply_hf_token(config)
    if not hasattr(model, "transcribe_longform"):
        raise RuntimeError("GigaAM model has no transcribe_longform")
    result = model.transcribe_longform(str(wav_path))
    segs = _segments_from_longform(result)
    if segs:
        return segs
    dur = _wav_duration_seconds(wav_path)
    return [ASRSegment(start=0.0, end=max(dur, 0.1), text="")]


def _transcribe_chunked_wav(model: Any, wav_path: Path) -> List[ASRSegment]:
    dur = _wav_duration_seconds(wav_path)
    chunk_s = _chunk_seconds()
    overlap_s = min(1.0, chunk_s * 0.1)
    step = max(chunk_s - overlap_s, 1.0)
    out: List[ASRSegment] = []
    t = 0.0
    while t < dur:
        end = min(t + chunk_s, dur)
        if end - t < 0.2:
            break
        clip: Path | None = None
        try:
            clip = _slice_wav(wav_path, t, end)
            text = _text_from_transcribe_result(model.transcribe(str(clip)))
            if text:
                out.append(ASRSegment(start=t, end=end, text=text))
        finally:
            if clip is not None:
                clip.unlink(missing_ok=True)
        if end >= dur:
            break
        t += step
    if not out:
        return [ASRSegment(start=0.0, end=max(dur, 0.1), text="")]
    return out


def transcribe_wav_to_segments(
    wav_path: Path,
    config: Dict[str, Any],
    language: Optional[str] = None,
) -> List[ASRSegment]:
    _warn_non_russian(language)
    model = get_gigaam_model(config)
    dur = _wav_duration_seconds(wav_path)
    if dur <= _MAX_SHORT_SECONDS:
        return _transcribe_short_wav(model, wav_path)
    if _longform_enabled(config):
        try:
            return _transcribe_longform_wav(model, wav_path, config)
        except Exception as e:
            logger.warning("GigaAM longform failed (%s); falling back to chunking", e)
    return _transcribe_chunked_wav(model, wav_path)


def transcribe_file_to_segments(
    audio_path: str,
    config: Dict[str, Any],
    language: Optional[str] = None,
    *,
    vad_preferences: Optional[dict] = None,
) -> List[ASRSegment]:
    del vad_preferences  # GigaAM has its own VAD in longform; chunk path ignores user VAD.
    from .audio_util import media_to_wav_16k_mono

    wav = media_to_wav_16k_mono(audio_path)
    try:
        return transcribe_wav_to_segments(wav, config, language=language)
    finally:
        wav.unlink(missing_ok=True)


def transcribe_bytes_to_text(
    audio_data: bytes,
    config: Dict[str, Any],
    language: Optional[str] = None,
    suffix: str = ".wav",
    *,
    vad_preferences: Optional[dict] = None,
) -> str:
    from .audio_util import bytes_to_tempfile, media_to_wav_16k_mono

    raw = bytes_to_tempfile(audio_data, suffix)
    wav: Path | None = None
    try:
        wav = media_to_wav_16k_mono(raw)
        dur = _wav_duration_seconds(wav)
        if dur > _MAX_SHORT_SECONDS:
            logger.warning(
                "GigaAM realtime chunk %.2fs exceeds short limit; truncating to %.2fs",
                dur,
                _MAX_SHORT_SECONDS,
            )
            clip = _slice_wav(wav, 0.0, _MAX_SHORT_SECONDS)
            try:
                segs = transcribe_wav_to_segments(clip, config, language=language)
            finally:
                clip.unlink(missing_ok=True)
        else:
            segs = transcribe_wav_to_segments(wav, config, language=language)
        return " ".join(s.text for s in segs).strip() or ""
    finally:
        raw.unlink(missing_ok=True)
        if wav is not None:
            wav.unlink(missing_ok=True)
