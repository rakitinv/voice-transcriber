"""
OAuth2 authentication endpoints.
"""

from __future__ import annotations

import os
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from core.config import app_config
from core.db import get_db
from core.logging import logger
from core.security import create_access_token
from ..models import User
from .dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _oauth_redirect_to_webui(access_token: str) -> RedirectResponse:
    """Send the browser back to the SPA with the JWT in the URL fragment."""
    webui = os.environ.get("VT_WEBUI_ORIGIN", "http://localhost:3002").strip().rstrip("/")
    return RedirectResponse(
        url=f"{webui}/login#access_token={quote(access_token, safe='')}",
        status_code=status.HTTP_302_FOUND,
    )


def _finalize_oauth_mock_login(db: Session, email: str, auth_provider: str) -> RedirectResponse:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(
            id=uuid4(),
            email=email,
            display_name="Test User",
            auth_provider=auth_provider,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    access_token = create_access_token(data={"sub": str(user.id)})
    return _oauth_redirect_to_webui(access_token)


@router.get("/me")
async def auth_me(current_user: Annotated[User, Depends(get_current_user)]):
    """Return the authenticated user (Bearer JWT)."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.display_name,
        "provider": current_user.auth_provider,
    }


@router.get("/google")
async def google_oauth_start():
    """Initiate Google OAuth flow."""
    # In production, generate a state token and store it in session/redis
    google_auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={app_config.auth.google.client_id}"
        "&redirect_uri=http://localhost:8002/api/auth/google/callback"
        "&response_type=code"
        "&scope=openid email profile"
    )
    return RedirectResponse(url=google_auth_url)


@router.get("/google/callback")
async def google_oauth_callback(
    code: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Handle Google OAuth callback.

    In production, this should:
    1. Exchange code for access token
    2. Fetch user info from Google
    3. Create or update user in database
    4. Issue JWT token
    """
    # TODO: Implement actual OAuth flow with httpx
    logger.warning("Google OAuth callback not fully implemented - using mock")

    # Mock user creation/retrieval
    email = "user@example.com"  # Would come from Google API
    return _finalize_oauth_mock_login(db, email, "google")


@router.get("/yandex")
async def yandex_oauth_start():
    """Initiate Yandex OAuth flow."""
    yandex_auth_url = (
        "https://oauth.yandex.ru/authorize"
        f"?client_id={app_config.auth.yandex.client_id}"
        "&redirect_uri=http://localhost:8002/api/auth/yandex/callback"
        "&response_type=code"
    )
    return RedirectResponse(url=yandex_auth_url)


@router.get("/yandex/callback")
async def yandex_oauth_callback(
    code: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Handle Yandex OAuth callback.

    In production, this should:
    1. Exchange code for access token
    2. Fetch user info from Yandex
    3. Create or update user in database
    4. Issue JWT token
    """
    # TODO: Implement actual OAuth flow with httpx
    logger.warning("Yandex OAuth callback not fully implemented - using mock")

    # Mock user creation/retrieval
    email = "user@yandex.ru"  # Would come from Yandex API
    return _finalize_oauth_mock_login(db, email, "yandex")
