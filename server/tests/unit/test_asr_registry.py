"""B1.5 / B3.4: registry загружает провайдеры; sample даёт реальный текст (не wired)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("faster_whisper")

from plugins.loader import plugin_registry

SAMPLE = Path(__file__).resolve().parents[1] / "sample-1.webm"


def test_registry_loads_default_whisper() -> None:
    p = plugin_registry.get_asr_provider()
    assert p is not None
    assert p.name == "whisper"


@pytest.mark.asr_inference
def test_registry_whisper_transcribe_sample_not_wired() -> None:
    import os

    from core.webm_pcm import ffmpeg_binary

    if os.environ.get("VT_SKIP_ASR_INFERENCE", "").lower() in ("1", "true", "yes"):
        pytest.skip("VT_SKIP_ASR_INFERENCE")
    if not ffmpeg_binary() or not SAMPLE.is_file():
        pytest.skip("ffmpeg or sample-1.webm missing")

    p = plugin_registry.get_asr_provider("whisper")
    assert p is not None
    segs = p.transcribe(str(SAMPLE))
    assert len(segs) >= 1
    text = " ".join(s.text for s in segs)
    assert "[ASR wired]" not in text
    assert len(text.strip()) >= 2


@pytest.mark.asr_inference
def test_transcribe_chunk_sample_not_wired() -> None:
    import os

    from core.webm_pcm import ffmpeg_binary

    if os.environ.get("VT_SKIP_ASR_INFERENCE", "").lower() in ("1", "true", "yes"):
        pytest.skip("VT_SKIP_ASR_INFERENCE")
    if not ffmpeg_binary() or not SAMPLE.is_file():
        pytest.skip("ffmpeg or sample-1.webm missing")

    p = plugin_registry.get_asr_provider()
    assert p is not None
    t = p.transcribe_chunk(SAMPLE.read_bytes())
    assert "[ASR wired]" not in t
    assert len(t.strip()) >= 2
