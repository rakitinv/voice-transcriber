"""Issue and rotate opaque service refresh tokens (C7.2)."""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import AuthRefreshSession, User


def _ttl_days() -> int:
    raw = (os.environ.get("VT_REFRESH_TOKEN_TTL_DAYS") or "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), 365))
    return 90


def mint_refresh_plaintext_and_hash() -> tuple[str, str]:
    plain = secrets.token_urlsafe(48)
    digest = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    return plain, digest


def issue_refresh_token(db: Session, *, user_id: uuid.UUID) -> str:
    """Persist a new refresh session; return plaintext for the client (caller commits)."""
    plain, digest = mint_refresh_plaintext_and_hash()
    now = datetime.now(timezone.utc)
    row = AuthRefreshSession(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash=digest,
        expires_at=now + timedelta(days=_ttl_days()),
        revoked_at=None,
        created_at=now,
    )
    db.add(row)
    db.commit()
    return plain


def rotate_refresh_token(db: Session, *, plaintext: str) -> tuple[User, str]:
    """Validate refresh, revoke row, issue new refresh; return (user, new_refresh_plaintext)."""
    digest = hashlib.sha256(plaintext.strip().encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    row = (
        db.query(AuthRefreshSession)
        .filter(AuthRefreshSession.token_hash == digest)
        .filter(AuthRefreshSession.revoked_at.is_(None))
        .first()
    )
    if row is None or row.expires_at <= now:
        raise ValueError("invalid_refresh")

    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        raise ValueError("invalid_refresh")

    row.revoked_at = now
    new_plain, new_digest = mint_refresh_plaintext_and_hash()
    new_row = AuthRefreshSession(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=new_digest,
        expires_at=now + timedelta(days=_ttl_days()),
        revoked_at=None,
        created_at=now,
    )
    db.add(new_row)
    db.commit()
    return user, new_plain
