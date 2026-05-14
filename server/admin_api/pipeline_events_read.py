"""Read pipeline_events for Admin API (§9-safe rows only)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import PipelineEvent


def count_pipeline_events(
    db: Session,
    *,
    conversation_id: UUID | None,
    event_type: str | None,
) -> int:
    q = db.query(func.count(PipelineEvent.id))
    if conversation_id is not None:
        q = q.filter(PipelineEvent.conversation_id == conversation_id)
    if event_type:
        q = q.filter(PipelineEvent.event_type == event_type.strip())
    return int(q.scalar() or 0)


def list_pipeline_events(
    db: Session,
    *,
    conversation_id: UUID | None,
    event_type: str | None,
    limit: int,
    offset: int,
) -> list[PipelineEvent]:
    q = db.query(PipelineEvent)
    if conversation_id is not None:
        q = q.filter(PipelineEvent.conversation_id == conversation_id)
    if event_type:
        q = q.filter(PipelineEvent.event_type == event_type.strip())
    q = q.order_by(PipelineEvent.created_at.desc(), PipelineEvent.id.desc())
    q = q.offset(offset).limit(limit)
    return list(q.all())


def list_pipeline_events_newer_than(
    db: Session,
    *,
    since_created_at: datetime,
    since_id: UUID,
    conversation_id: UUID | None,
    event_type: str | None,
    limit: int,
) -> list[PipelineEvent]:
    """Rows strictly after (since_created_at, since_id), newest last (append order)."""
    q = db.query(PipelineEvent).filter(
        or_(
            PipelineEvent.created_at > since_created_at,
            (PipelineEvent.created_at == since_created_at) & (PipelineEvent.id > since_id),
        )
    )
    if conversation_id is not None:
        q = q.filter(PipelineEvent.conversation_id == conversation_id)
    if event_type:
        q = q.filter(PipelineEvent.event_type == event_type.strip())
    q = q.order_by(PipelineEvent.created_at.asc(), PipelineEvent.id.asc())
    q = q.limit(limit)
    return list(q.all())
