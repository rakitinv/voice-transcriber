"""
Realtime: распознавание одного чанка байтов без Celery/S3 (для WebSocket и Celery-задачи).

Текст заглушки синхронизирован с workers.tasks.asr.STUB_TRANSCRIPT.
"""

from __future__ import annotations

from plugins.loader import plugin_registry

from .logging import logger
from .pcm_audio import pcm_s16le_mono_to_wav

STUB_CHUNK_TEXT = (
    "[stub ASR] No provider configured; placeholder transcript (Phase A)."
)


def _transcribe_chunk_blob(
    audio_data: bytes,
    language: str | None = None,
    *,
    vad_preferences: dict | None = None,
) -> str:
    try:
        provider = plugin_registry.get_asr_provider(tier="realtime")
        if not provider:
            return STUB_CHUNK_TEXT
        return provider.transcribe_chunk(
            audio_data, language=language, vad_preferences=vad_preferences
        )
    except Exception as e:
        logger.error("Chunk transcription failed: %s", e)
        raise


def transcribe_audio_chunk_bytes(
    audio_data: bytes,
    language: str | None = None,
    *,
    vad_preferences: dict | None = None,
) -> str:
    """
    Синхронный вызов провайдера ASR для короткого фрагмента (произвольные байты: WebM, WAV и т.д.).
    """
    return _transcribe_chunk_blob(audio_data, language, vad_preferences=vad_preferences)


def transcribe_pcm_s16le_chunk(
    pcm: bytes,
    language: str | None = None,
    sample_rate: int = 16_000,
    *,
    vad_preferences: dict | None = None,
) -> str:
    """PCM s16le mono → WAV → провайдер (realtime после ffmpeg)."""
    if not pcm:
        return STUB_CHUNK_TEXT
    wav = pcm_s16le_mono_to_wav(pcm, sample_rate)
    return _transcribe_chunk_blob(wav, language, vad_preferences=vad_preferences)
