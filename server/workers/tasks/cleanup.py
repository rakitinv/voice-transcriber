"""
TTL cleanup tasks.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_

from ..celery_app import celery_app
from app.models import Conversation
from core.config import app_config
from core.db import session_scope
from core.logging import logger
from core.s3 import storage


@celery_app.task(name="workers.tasks.cleanup.expired_conversations", bind=True)
def cleanup_expired_conversations(self) -> dict:
    """
    Clean up conversations that have exceeded their TTL.

    Returns:
        Dictionary with cleanup result
    """
    logger.info("Starting TTL cleanup job")

    try:
        max_ttl = timedelta(days=app_config.limits.max_ttl_days)
        cutoff_date = datetime.utcnow() - max_ttl

        deleted_count = 0

        with session_scope() as session:
            # Find expired conversations
            expired = session.query(Conversation).filter(
                and_(
                    Conversation.created_at < cutoff_date,
                    Conversation.deleted_at.is_(None),
                )
            ).all()

            for conversation in expired:
                try:
                    # Delete from S3
                    storage.delete_conversation(conversation.user_id, str(conversation.id))

                    # Mark as deleted in DB
                    conversation.deleted_at = datetime.utcnow()
                    session.commit()

                    deleted_count += 1
                    logger.info(
                        f"Deleted expired conversation {conversation.id} "
                        f"(user: {conversation.user_id})"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to delete conversation {conversation.id}: {e}"
                    )
                    session.rollback()

        logger.info(f"TTL cleanup completed: {deleted_count} conversations deleted")
        return {"status": "success", "deleted_count": deleted_count}

    except Exception as e:
        logger.error(f"TTL cleanup failed: {e}")
        raise


@celery_app.task(name="workers.tasks.cleanup.schedule_cleanup", bind=True)
def schedule_cleanup(self) -> dict:
    """
    Periodic task to schedule cleanup (runs daily).

    This task should be scheduled via Celery Beat.
    """
    cleanup_expired_conversations.delay()
    return {"status": "scheduled"}
