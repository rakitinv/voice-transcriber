"""Audit trail for admin API (ADMIN_OPS_CONSOLE §8)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.models import AdminAuditEvent
from core.db import session_scope
from core.logging import logger

_MAX_DETAIL_LEN = 8000


def _clip_detail(detail: str | None) -> str | None:
    if detail is None:
        return None
    s = detail.strip()
    if not s:
        return None
    if len(s) > _MAX_DETAIL_LEN:
        return s[: _MAX_DETAIL_LEN - 1] + "…"
    return s


def record_admin_audit_event(
    *,
    admin_user_id: UUID,
    action: str,
    conversation_id: UUID | None = None,
    detail: str | None = None,
) -> None:
    act = (action or "").strip()[:128]
    if not act:
        act = "unknown"
    det = _clip_detail(detail)
    base = "admin_audit_event admin_user_id=%s action=%s conversation_id=%s"
    args: tuple[object, ...] = (
        str(admin_user_id),
        act,
        str(conversation_id) if conversation_id else "",
    )
    if det:
        logger.info(base + " detail=%s", *args, det)
    else:
        logger.info(base, *args)
    with session_scope() as db:
        db.add(
            AdminAuditEvent(
                id=uuid4(),
                admin_user_id=admin_user_id,
                action=act,
                conversation_id=conversation_id,
                detail=det,
                created_at=datetime.now(timezone.utc),
            )
        )
