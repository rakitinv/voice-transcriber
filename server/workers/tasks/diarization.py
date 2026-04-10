"""
Speaker diarization tasks.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..celery_app import celery_app
from core.logging import logger
from core.s3 import storage


@celery_app.task(name="workers.tasks.diarization.run_diarization", bind=True)
def run_diarization(
    self, user_id: str, conversation_id: str
) -> dict:
    """
    Run speaker diarization on a conversation.

    Args:
        user_id: User ID
        conversation_id: Conversation ID

    Returns:
        Dictionary with diarization result
    """
    logger.info(f"Starting diarization for conversation {conversation_id}")

    try:
        # Download audio and transcript
        audio_data = storage.download_audio(user_id, conversation_id, decrypt=True)
        transcript = storage.download_transcript_json(user_id, conversation_id, decrypt=True)

        # Save audio to temporary file
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_path.write_bytes(audio_data)

        try:
            # TODO: Implement diarization provider loading and execution
            # For now, this is a placeholder
            logger.warning("Diarization not yet implemented - returning transcript as-is")

            # Merge transcript segments with speaker labels (placeholder)
            diarized_segments = []
            for seg in transcript.get("segments", []):
                diarized_segments.append({
                    "speaker": "Speaker 1",  # Placeholder
                    "start": seg.get("start", 0.0),
                    "end": seg.get("end", 0.0),
                    "text": seg.get("text", ""),
                })

            # Update transcript with diarization
            transcript["segments"] = diarized_segments

            # Upload updated transcript
            storage.upload_transcript_json(transcript, user_id, conversation_id, encrypt=True)

            logger.info(f"Completed diarization for conversation {conversation_id}")
            return {"status": "success", "speakers_count": 1}

        finally:
            tmp_path.unlink()

    except Exception as e:
        logger.error(f"Diarization failed for {conversation_id}: {e}")
        raise
