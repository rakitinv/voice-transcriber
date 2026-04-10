"""
ASR transcription tasks.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..celery_app import celery_app
from core.logging import logger
from core.s3 import storage
from plugins.loader import plugin_registry


@celery_app.task(name="workers.tasks.asr.transcribe_file", bind=True)
def transcribe_file(
    self, user_id: str, conversation_id: str, language: str | None = None
) -> dict:
    """
    Transcribe an audio file using the configured ASR provider.

    Args:
        user_id: User ID
        conversation_id: Conversation ID
        language: Optional language code

    Returns:
        Dictionary with transcription result
    """
    logger.info(f"Starting ASR transcription for conversation {conversation_id}")

    try:
        # Download audio from S3
        audio_data = storage.download_audio(user_id, conversation_id, decrypt=True)

        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_path.write_bytes(audio_data)

        try:
            # Get ASR provider
            provider = plugin_registry.get_asr_provider()
            if not provider:
                raise ValueError("No ASR provider available")

            # Transcribe
            segments = provider.transcribe(str(tmp_path), language=language)

            # Convert to dict format
            transcript = {
                "segments": [seg.to_dict() if hasattr(seg, "to_dict") else seg for seg in segments]
            }

            # Upload transcript to S3
            storage.upload_transcript_json(transcript, user_id, conversation_id, encrypt=True)

            logger.info(f"Completed ASR transcription for conversation {conversation_id}")
            return {"status": "success", "segments_count": len(segments)}

        finally:
            # Clean up temp file
            tmp_path.unlink()

    except Exception as e:
        logger.error(f"ASR transcription failed for {conversation_id}: {e}")
        raise


@celery_app.task(name="workers.tasks.asr.transcribe_chunk", bind=True)
def transcribe_chunk(
    self, audio_data: bytes, language: str | None = None
) -> str:
    """
    Transcribe a small audio chunk (for realtime mode).

    Args:
        audio_data: Raw audio bytes
        language: Optional language code

    Returns:
        Transcribed text
    """
    try:
        provider = plugin_registry.get_asr_provider()
        if not provider:
            raise ValueError("No ASR provider available")

        return provider.transcribe_chunk(audio_data, language=language)
    except Exception as e:
        logger.error(f"Chunk transcription failed: {e}")
        raise
