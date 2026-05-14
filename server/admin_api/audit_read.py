"""Read-only queries for admin audit events."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AdminAuditEvent


def count_admin_audit_events(
    db: Session,
    *,
    action: str | None,
    conversation_id: UUID | None,
    admin_user_id: UUID | None,
) -> int:
    q = db.query(AdminAuditEvent)
    if action:
        q = q.filter(AdminAuditEvent.action == action)
    if conversation_id is not None:
        q = q.filter(AdminAuditEvent.conversation_id == conversation_id)
    if admin_user_id is not None:
        q = q.filter(AdminAuditEvent.admin_user_id == admin_user_id)
    return int(q.count())


def list_admin_audit_events(
    db: Session,
    *,
    action: str | None,
    conversation_id: UUID | None,
    admin_user_id: UUID | None,
    limit: int,
    offset: int,
) -> list[AdminAuditEvent]:
    q = db.query(AdminAuditEvent)
    if action:
        q = q.filter(AdminAuditEvent.action == action)
    if conversation_id is not None:
        q = q.filter(AdminAuditEvent.conversation_id == conversation_id)
    if admin_user_id is not None:
        q = q.filter(AdminAuditEvent.admin_user_id == admin_user_id)
    return (
        q.order_by(AdminAuditEvent.created_at.desc(), AdminAuditEvent.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
