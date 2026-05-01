"""PCM s16le mono helpers (realtime ASR после WebM/Opus → PCM)."""

from __future__ import annotations

import io
import wave


def pcm_s16le_mono_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Оборачивает сырые PCM-кадры в WAV (моно, 16 bit) для `transcribe_chunk`."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()
