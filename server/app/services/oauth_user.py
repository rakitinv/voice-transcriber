"""Resolve VT user from OAuth profile using `(provider, provider_subject)` (C7.1)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import User, UserOAuthIdentity
from .oauth_exchange import OAuthProfile


def upsert_user_from_oauth_profile(db: Session, *, provider: str, profile: OAuthProfile) -> User:
    """
    Find user by OAuth identity; otherwise create user + identity.

    If the identity is unknown but **email** already belongs to another user → **409**
    (account linking is Web UI only — C7.4).
    """
    subject = profile.subject.strip()
    if not subject:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth profile missing subject")

    identity = (
        db.query(UserOAuthIdentity)
        .filter(
            UserOAuthIdentity.provider == provider,
            UserOAuthIdentity.provider_subject == subject,
        )
        .first()
    )

    email = profile.email.strip()
    if not email:
        email = f"{provider}.{subject}@oauth.placeholder.local"

    display = profile.display_name
    if display is not None:
        display = display.strip() or None

    if identity:
        user = db.query(User).filter(User.id == identity.user_id).first()
        if user is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="OAuth identity orphan")
        changed = False
        if user.email != email:
            user.email = email
            changed = True
        if display and user.display_name != display:
            user.display_name = display
            changed = True
        if user.auth_provider != provider:
            user.auth_provider = provider
            changed = True
        if identity.provider_email != email:
            identity.provider_email = email
            changed = True
        if changed:
            db.commit()
            db.refresh(user)
            db.refresh(identity)
        return user

    other = db.query(User).filter(User.email == email).first()
    if other is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This email is already registered to another account. "
                "Sign in via Web UI and link providers there (see docs/AUTH_AND_IDENTITY.md)."
            ),
        )

    user = User(
        id=uuid4(),
        email=email,
        display_name=display or email.split("@", 1)[0],
        auth_provider=provider,
    )
    oid = UserOAuthIdentity(
        id=uuid4(),
        user_id=user.id,
        provider=provider,
        provider_subject=subject,
        provider_email=email,
    )
    db.add(user)
    db.add(oid)
    db.commit()
    db.refresh(user)
    return user
