"""
TTL cleanup tasks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete

from ..celery_app import celery_app
from app.models import AuthSigninEvent, Conversation, PipelineEvent
from core.config import app_config
from core.db import session_scope
from core.logging import logger
from core.s3 import storage


@celery_app.task(name="workers.tasks.cleanup.old_auth_signin_events", bind=True)
def cleanup_old_auth_signin_events(self) -> dict:
    """
    Delete product login audit rows older than ``auth.login_audit.retention_days``.

    ``retention_days <= 0`` disables this job (no automatic deletion).
    """
    days = int(app_config.auth.login_audit.retention_days)
    if days <= 0:
        logger.info("auth_signin_events cleanup skipped (retention_days<=0)")
        return {"status": "skipped", "deleted": 0, "reason": "retention_disabled"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with session_scope() as session:
            res = session.execute(delete(AuthSigninEvent).where(AuthSigninEvent.created_at < cutoff))
            deleted = res.rowcount or 0
        logger.info("auth_signin_events cleanup: deleted %s rows older than %s days", deleted, days)
        return {"status": "success", "deleted": deleted, "cutoff": cutoff.isoformat()}
    except Exception as e:
        logger.error("auth_signin_events cleanup failed: %s", e)
        raise


@celery_app.task(name="workers.tasks.cleanup.old_pipeline_events", bind=True)
def cleanup_old_pipeline_events(self) -> dict:
    """
    Delete pipeline_events rows older than ``auth.login_audit.retention_days``.

    Same retention knob as auth_signin_events (``VT_AUTH_SIGNIN_EVENTS_RETENTION_DAYS`` / YAML
    ``auth.login_audit.retention_days``). ``retention_days <= 0`` disables this job.
    """
    days = int(app_config.auth.login_audit.retention_days)
    if days <= 0:
        logger.info("pipeline_events cleanup skipped (retention_days<=0)")
        return {"status": "skipped", "deleted": 0, "reason": "retention_disabled"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with session_scope() as session:
            res = session.execute(delete(PipelineEvent).where(PipelineEvent.created_at < cutoff))
            deleted = res.rowcount or 0
        logger.info("pipeline_events cleanup: deleted %s rows older than %s days", deleted, days)
        return {"status": "success", "deleted": deleted, "cutoff": cutoff.isoformat()}
    except Exception as e:
        logger.error("pipeline_events cleanup failed: %s", e)
        raise


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
    cleanup_old_auth_signin_events.delay()
    cleanup_old_pipeline_events.delay()
    return {"status": "scheduled"}
