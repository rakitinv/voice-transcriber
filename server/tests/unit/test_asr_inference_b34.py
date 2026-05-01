"""
B3.4: реальный inference; эталон `server/tests/sample-1.webm`.

Пропуск: `VT_SKIP_ASR_INFERENCE=1` или нет ffmpeg.
Vosk: только при заданном `VOSK_MODEL_PATH` (каталог распакованной модели).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("faster_whisper")

from app.asr.faster_whisper import FasterWhisperASRProvider
from app.asr.vosk import VoskASRProvider
from app.asr.whisper import WhisperASRProvider
from core.webm_pcm import ffmpeg_binary

SAMPLE = Path(__file__).resolve().parents[1] / "sample-1.webm"

# Минимальная модель для скорости CI/локально (перекрывает base из прод-конфига)
TINY = {"model": "tiny", "enabled": True}


def _skip_env() -> None:
    if os.environ.get("VT_SKIP_ASR_INFERENCE", "").lower() in ("1", "true", "yes"):
        pytest.skip("VT_SKIP_ASR_INFERENCE set")
    if not ffmpeg_binary():
        pytest.skip("ffmpeg not on PATH (ASR tests need ffmpeg)")
    if not SAMPLE.is_file():
        pytest.skip(f"missing sample: {SAMPLE}")


def _assert_real_segments(segs: list) -> None:
    assert len(segs) >= 1
    text = " ".join(s.text for s in segs)
    assert "[ASR wired]" not in text
    assert len(text.strip()) >= 2


@pytest.mark.asr_inference
def test_whisper_transcribes_sample_webm() -> None:
    _skip_env()
    p = WhisperASRProvider({**TINY, "model_path": None})
    segs = p.transcribe(str(SAMPLE))
    _assert_real_segments(segs)


@pytest.mark.asr_inference
def test_faster_whisper_provider_transcribes_sample_webm() -> None:
    _skip_env()
    p = FasterWhisperASRProvider({**TINY, "model_path": None})
    segs = p.transcribe(str(SAMPLE))
    _assert_real_segments(segs)


@pytest.mark.asr_inference
def test_vosk_transcribes_sample_when_model_configured() -> None:
    _skip_env()
    vdir = os.environ.get("VOSK_MODEL_PATH", "").strip()
    if not vdir or not Path(vdir).is_dir():
        pytest.skip("VOSK_MODEL_PATH not set or not a directory")
    p = VoskASRProvider({"enabled": True, "model": "default", "model_path": vdir})
    segs = p.transcribe(str(SAMPLE))
    _assert_real_segments(segs)


@pytest.mark.asr_inference
def test_whisper_chunk_from_sample_bytes() -> None:
    _skip_env()
    data = SAMPLE.read_bytes()
    p = WhisperASRProvider({**TINY, "model_path": None})
    text = p.transcribe_chunk(data)
    assert "[ASR wired]" not in text
    assert len(text.strip()) >= 2
