"""
FastAPI dependencies for authentication and authorization.
"""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from core.config import app_config
from core.db import get_db
from core.security import decode_access_token

from ..services.auth_client_meta import client_fingerprint, client_ip_from_request
from ..services.auth_credential_lockout import is_api_key_blocked, register_api_key_failure
from ..services.auth_signin_audit import record_auth_signin_event
from ..models import User, UserApiKey

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(security)
    ],
    db: Annotated[Session, Depends(get_db)],
    x_vt_api_key: Annotated[str | None, Header(alias="X-VT-Api-Key")] = None,
) -> User:
    """
    Authenticate via Bearer JWT or ``X-VT-Api-Key`` (Phase C6).

    Raises:
        HTTPException: If token is invalid or user not found
    """
    raw_key = (x_vt_api_key or "").strip()
    ip = client_ip_from_request(request)
    fp = client_fingerprint(ip)
    ra = int(app_config.auth.lockout.block_seconds)
    if raw_key:
        if is_api_key_blocked(ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many invalid API key attempts; try again later",
                headers={"Retry-After": str(ra)},
            )
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        row = db.query(UserApiKey).filter(UserApiKey.key_hash == digest).first()
        if row is None:
            now_blocked = register_api_key_failure(ip)
            record_auth_signin_event(
                outcome="failure",
                channel="api_key",
                reason_code="invalid_api_key",
                client_fingerprint=fp,
            )
            if now_blocked or is_api_key_blocked(ip):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many invalid API key attempts; try again later",
                    headers={"Retry-After": str(ra)},
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
        user = db.query(User).filter(User.id == row.user_id).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        return user

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_access_token(token)
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

    user = db.query(User).filter(User.id == UUID(user_id)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user
