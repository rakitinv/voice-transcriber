"""
Admin API auth: same JWT verification as the product API + admin_memberships row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.models import AdminMembership, User
from core.db import get_db
from core.security import decode_access_token

security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AdminPrincipal:
    user: User
    membership: AdminMembership


async def require_admin_principal(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(security)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> AdminPrincipal:
    """
    Authenticate with Bearer JWT only (no API keys on admin routes for MVP).

    Admin API accepts the same access tokens as the main API; authorization
    requires a row in ``admin_memberships``.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = db.query(User).filter(User.id == UUID(str(user_id))).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    membership = (
        db.query(AdminMembership).filter(AdminMembership.user_id == user.id).first()
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin membership required",
        )

    return AdminPrincipal(user=user, membership=membership)
