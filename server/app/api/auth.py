"""
OAuth2 authentication endpoints (C7.1 real exchange, C7.3 PKCE + signed state).
"""

from __future__ import annotations

import os
from typing import Annotated
from urllib.parse import parse_qs, quote, urlencode
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import app_config
from core.db import get_db
from core.logging import logger
from core.oauth_public import oauth_public_api_origin
from core.oauth_state import mint_extension_oauth_state, mint_web_oauth_state, parse_extension_oauth_state, parse_web_oauth_state
from core.security import create_access_token
from ..models import User
from ..services.oauth_exchange import OAuthExchangeError, exchange_google_authorization_code, exchange_yandex_authorization_code
from ..services.oauth_user import upsert_user_from_oauth_profile
from .dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class ExtensionAuthUrlResponse(BaseModel):
    auth_url: str


class ExtensionFinalizeResponse(BaseModel):
    access_token: str
    user: dict


def _is_allowed_extension_redirect(url: str) -> bool:
    from urllib.parse import urlparse

    u = urlparse((url or "").strip())
    return bool(u.scheme == "https" and u.netloc.endswith(".chromiumapp.org"))


def _web_oauth_callback_uri(provider: str) -> str:
    return f"{oauth_public_api_origin()}/api/auth/{provider}/callback"


def _oauth_redirect_to_webui(access_token: str) -> RedirectResponse:
    """Send the browser back to the SPA with the JWT in the URL fragment."""
    webui = os.environ.get("VT_WEBUI_ORIGIN", "http://localhost:3002").strip().rstrip("/")
    return RedirectResponse(
        url=f"{webui}/login#access_token={quote(access_token, safe='')}",
        status_code=status.HTTP_302_FOUND,
    )


def _oauth_redirect_to_extension(access_token: str, next_url: str) -> RedirectResponse:
    """
    Send the browser back to the browser-extension web auth flow.

    `chrome.identity.launchWebAuthFlow` expects the final redirect to land on a
    URL under `https://<extension-id>.chromiumapp.org/*`.
    """
    from urllib.parse import urlparse

    u = urlparse((next_url or "").strip())
    if not (u.scheme == "https" and u.netloc.endswith(".chromiumapp.org")):
        return _oauth_redirect_to_webui(access_token)

    sep = "&" if ("#" in next_url) else "#"
    return RedirectResponse(
        url=f"{next_url}{sep}access_token={quote(access_token, safe='')}",
        status_code=status.HTTP_302_FOUND,
    )


def _parse_legacy_web_state(state: str | None) -> tuple[str | None, str | None]:
    """Phase B state: URL-encoded client/next inside `state` query param."""
    if not state:
        return None, None
    try:
        q = parse_qs(state, keep_blank_values=True)
        return (q.get("client", [None])[0] or None), (q.get("next", [None])[0] or None)
    except Exception:
        return None, None


def _decode_web_oauth_state(
    state: str | None, *, expected_provider: str | None = None
) -> tuple[str | None, str | None]:
    if not state:
        return None, None
    try:
        payload = parse_web_oauth_state(state)
        if expected_provider and payload.get("provider") != expected_provider:
            raise HTTPException(status_code=400, detail="state provider mismatch")
        return (payload.get("client") or None) or None, (payload.get("next") or None) or None
    except HTTPException:
        raise
    except ValueError:
        return _parse_legacy_web_state(state)


async def _issue_redirect_after_web_oauth(
    db: Session,
    *,
    provider: str,
    code: str,
    redirect_uri: str,
    client: str | None,
    next_url: str | None,
) -> RedirectResponse:
    try:
        if provider == "google":
            profile = await exchange_google_authorization_code(
                code=code, redirect_uri=redirect_uri, code_verifier=None
            )
        elif provider == "yandex":
            profile = await exchange_yandex_authorization_code(
                code=code, redirect_uri=redirect_uri, code_verifier=None
            )
        else:
            raise HTTPException(status_code=400, detail="unknown_provider")
    except OAuthExchangeError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    user = upsert_user_from_oauth_profile(db, provider=provider, profile=profile)
    access_token = create_access_token(data={"sub": str(user.id)})
    if (client or "").strip().lower() == "extension" and next_url:
        return _oauth_redirect_to_extension(access_token, next_url)
    return _oauth_redirect_to_webui(access_token)


async def _finalize_extension_json(
    db: Session, *, provider: str, code: str, redirect_uri: str, code_verifier: str
) -> ExtensionFinalizeResponse:
    try:
        if provider == "google":
            profile = await exchange_google_authorization_code(
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
        elif provider == "yandex":
            profile = await exchange_yandex_authorization_code(
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
        else:
            raise HTTPException(status_code=400, detail="unknown_provider")
    except OAuthExchangeError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    user = upsert_user_from_oauth_profile(db, provider=provider, profile=profile)
    access_token = create_access_token(data={"sub": str(user.id)})
    return ExtensionFinalizeResponse(
        access_token=access_token,
        user={
            "id": str(user.id),
            "email": user.email,
            "name": user.display_name,
            "provider": user.auth_provider,
        },
    )


def _build_google_extension_authorize_url(
    *,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    state_jwt: str,
    ux_mode: str,
    account_prompt: str,
) -> str:
    params: dict[str, str] = {
        "client_id": app_config.auth.google.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "state": state_jwt,
    }
    if ux_mode == "silent":
        params["prompt"] = "none"
    elif account_prompt == "force":
        params["prompt"] = "select_account consent"
    else:
        params["prompt"] = "select_account"
    q = urlencode(params, quote_via=quote)
    return f"https://accounts.google.com/o/oauth2/v2/auth?{q}"


def _build_yandex_extension_authorize_url(
    *,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    state_jwt: str,
    ux_mode: str,
    account_prompt: str,
) -> str:
    params: dict[str, str] = {
        "client_id": app_config.auth.yandex.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "state": state_jwt,
    }
    if ux_mode == "interactive" and account_prompt == "force":
        params["force_confirm"] = "yes"
    q = urlencode(params, quote_via=quote)
    return f"https://oauth.yandex.ru/authorize?{q}"


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
async def google_oauth_start(
    client: str | None = None,
    next: str | None = None,  # noqa: A002
):
    """Initiate Google OAuth flow."""
    cb = _web_oauth_callback_uri("google")
    state = mint_web_oauth_state(provider="google", client=client, next_url=next)
    params = {
        "client_id": app_config.auth.google.client_id,
        "redirect_uri": cb,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    }
    google_auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params, quote_via=quote)
    return RedirectResponse(url=google_auth_url)


@router.get("/google/extension/start", response_model=ExtensionAuthUrlResponse)
async def google_extension_start(
    redirect_uri: str = Query(..., description="chrome.identity.getRedirectURL(...)"),
    code_challenge: str = Query(..., min_length=43, max_length=128),
    code_challenge_method: str = Query("S256", description="Only S256 supported"),
    ux_mode: str = Query("interactive", description="silent | interactive"),
    account_prompt: str = Query("normal", description="normal | force — stronger account picker hints"),
):
    if code_challenge_method.upper() != "S256":
        raise HTTPException(status_code=400, detail="Only code_challenge_method=S256 is supported")
    if ux_mode not in ("silent", "interactive"):
        raise HTTPException(status_code=400, detail="ux_mode must be silent or interactive")
    if account_prompt not in ("normal", "force"):
        raise HTTPException(status_code=400, detail="account_prompt must be normal or force")
    if not _is_allowed_extension_redirect(redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    state_jwt = mint_extension_oauth_state(
        provider="google",
        redirect_uri=redirect_uri.strip(),
        ux_mode=ux_mode,
        account_prompt=account_prompt,
    )
    auth_url = _build_google_extension_authorize_url(
        redirect_uri=redirect_uri.strip(),
        code_challenge=code_challenge.strip(),
        code_challenge_method="S256",
        state_jwt=state_jwt,
        ux_mode=ux_mode,
        account_prompt=account_prompt,
    )
    return ExtensionAuthUrlResponse(auth_url=auth_url)


@router.get("/google/callback")
async def google_oauth_callback(
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    if error and not code:
        msg = error_description or error
        logger.warning("Google OAuth callback error: %s", msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"OAuth provider error: {msg}")
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing authorization code")
    client, next_url = _decode_web_oauth_state(state, expected_provider="google")
    cb = _web_oauth_callback_uri("google")
    return await _issue_redirect_after_web_oauth(
        db,
        provider="google",
        code=code,
        redirect_uri=cb,
        client=client,
        next_url=next_url,
    )


@router.post("/google/extension/finalize", response_model=ExtensionFinalizeResponse)
async def google_extension_finalize(
    db: Annotated[Session, Depends(get_db)],
    code: str = Query(...),
    code_verifier: str = Query(..., min_length=43, max_length=128),
    state: str = Query(...),
):
    try:
        payload = parse_extension_oauth_state(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid or expired state") from None
    if payload.get("provider") != "google":
        raise HTTPException(status_code=400, detail="state provider mismatch")
    redirect_uri = (payload.get("ru") or "").strip()
    if not redirect_uri or not _is_allowed_extension_redirect(redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri in state")

    return await _finalize_extension_json(
        db,
        provider="google",
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier.strip(),
    )


@router.get("/yandex")
async def yandex_oauth_start(
    client: str | None = None,
    next: str | None = None,  # noqa: A002
):
    """Initiate Yandex OAuth flow."""
    cb = _web_oauth_callback_uri("yandex")
    state = mint_web_oauth_state(provider="yandex", client=client, next_url=next)
    params = {
        "client_id": app_config.auth.yandex.client_id,
        "redirect_uri": cb,
        "response_type": "code",
        "state": state,
    }
    yandex_auth_url = "https://oauth.yandex.ru/authorize?" + urlencode(params, quote_via=quote)
    return RedirectResponse(url=yandex_auth_url)


@router.get("/yandex/extension/start", response_model=ExtensionAuthUrlResponse)
async def yandex_extension_start(
    redirect_uri: str = Query(..., description="chrome.identity.getRedirectURL(...)"),
    code_challenge: str = Query(..., min_length=43, max_length=128),
    code_challenge_method: str = Query("S256"),
    ux_mode: str = Query("interactive"),
    account_prompt: str = Query("normal"),
):
    if code_challenge_method.upper() != "S256":
        raise HTTPException(status_code=400, detail="Only code_challenge_method=S256 is supported")
    if ux_mode not in ("silent", "interactive"):
        raise HTTPException(status_code=400, detail="ux_mode must be silent or interactive")
    if account_prompt not in ("normal", "force"):
        raise HTTPException(status_code=400, detail="account_prompt must be normal or force")
    if not _is_allowed_extension_redirect(redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    state_jwt = mint_extension_oauth_state(
        provider="yandex",
        redirect_uri=redirect_uri.strip(),
        ux_mode=ux_mode,
        account_prompt=account_prompt,
    )
    auth_url = _build_yandex_extension_authorize_url(
        redirect_uri=redirect_uri.strip(),
        code_challenge=code_challenge.strip(),
        code_challenge_method="S256",
        state_jwt=state_jwt,
        ux_mode=ux_mode,
        account_prompt=account_prompt,
    )
    return ExtensionAuthUrlResponse(auth_url=auth_url)


@router.get("/yandex/callback")
async def yandex_oauth_callback(
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    if error and not code:
        msg = error_description or error
        logger.warning("Yandex OAuth callback error: %s", msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"OAuth provider error: {msg}")
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing authorization code")
    client, next_url = _decode_web_oauth_state(state, expected_provider="yandex")
    cb = _web_oauth_callback_uri("yandex")
    return await _issue_redirect_after_web_oauth(
        db,
        provider="yandex",
        code=code,
        redirect_uri=cb,
        client=client,
        next_url=next_url,
    )


@router.post("/yandex/extension/finalize", response_model=ExtensionFinalizeResponse)
async def yandex_extension_finalize(
    db: Annotated[Session, Depends(get_db)],
    code: str = Query(...),
    code_verifier: str = Query(..., min_length=43, max_length=128),
    state: str = Query(...),
):
    try:
        payload = parse_extension_oauth_state(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid or expired state") from None
    if payload.get("provider") != "yandex":
        raise HTTPException(status_code=400, detail="state provider mismatch")
    redirect_uri = (payload.get("ru") or "").strip()
    if not redirect_uri or not _is_allowed_extension_redirect(redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri in state")

    return await _finalize_extension_json(
        db,
        provider="yandex",
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier.strip(),
    )
