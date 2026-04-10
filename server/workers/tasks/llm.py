"""
LLM summary generation tasks.
"""

from __future__ import annotations

from ..celery_app import celery_app
from core.logging import logger
from core.s3 import storage
from plugins.loader import plugin_registry


@celery_app.task(name="workers.tasks.llm.generate_summary", bind=True)
def generate_summary(
    self, user_id: str, conversation_id: str
) -> dict:
    """
    Generate a summary for a conversation using the configured LLM provider.

    Args:
        user_id: User ID
        conversation_id: Conversation ID

    Returns:
        Dictionary with summary result
    """
    logger.info(f"Starting summary generation for conversation {conversation_id}")

    try:
        # Download transcript
        transcript = storage.download_transcript_json(user_id, conversation_id, decrypt=True)

        # Get LLM provider
        provider = plugin_registry.get_llm_provider()
        if not provider:
            raise ValueError("No LLM provider available")

        # Generate summary
        summary_text = provider.summarize(transcript)

        # Upload summary to S3
        storage.upload_summary(summary_text, user_id, conversation_id, encrypt=True)

        logger.info(f"Completed summary generation for conversation {conversation_id}")
        return {"status": "success", "summary_length": len(summary_text)}

    except Exception as e:
        logger.error(f"Summary generation failed for {conversation_id}: {e}")
        raise
