"""Persist auth_signin_events in an independent transaction."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.models import AuthSigninEvent
from core.config import app_config
from core.db import session_scope
from core.logging import logger


def record_auth_signin_event(
    *,
    outcome: str,
    channel: str,
    reason_code: str | None = None,
    provider: str | None = None,
    user_id: UUID | None = None,
    client_fingerprint: str | None = None,
) -> None:
    if not app_config.auth.login_audit.enabled:
        return
    oc = (outcome or "").strip().lower()[:16]
    ch = (channel or "").strip()[:32]
    if oc not in ("success", "failure"):
        oc = "failure"
    if not ch:
        ch = "unknown"
    rc = (reason_code or "").strip()[:64] or None
    pv = (provider or "").strip()[:32] or None
    fp = None
    if app_config.auth.login_audit.include_client_fingerprint:
        fp = (client_fingerprint or "").strip()[:64] or None
    try:
        with session_scope() as db:
            db.add(
                AuthSigninEvent(
                    id=uuid4(),
                    created_at=datetime.now(timezone.utc),
                    outcome=oc,
                    channel=ch,
                    reason_code=rc,
                    provider=pv,
                    user_id=user_id,
                    client_fingerprint=fp,
                )
            )
    except Exception:
        logger.warning("auth_signin_event persist failed", exc_info=True)
