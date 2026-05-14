"""
OAuth2 authentication endpoints (C7.1 real exchange, C7.3 PKCE + signed state).
"""

from __future__ import annotations

import os
from typing import Annotated
from urllib.parse import parse_qs, quote, urlencode
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import app_config
from core.db import get_db
from core.logging import logger
from core.oauth_admin_webui import is_allowed_admin_oauth_next
from core.oauth_public import oauth_public_api_origin
from core.oauth_state import (
    mint_extension_oauth_state,
    mint_web_link_oauth_state,
    mint_web_oauth_state,
    parse_extension_oauth_state,
    parse_web_link_oauth_state,
    parse_web_oauth_state,
)
from core.security import create_access_token
from ..models import User
from ..services.auth_client_meta import client_fingerprint, client_ip_from_request
from ..services.auth_credential_lockout import (
    clear_refresh_failures,
    is_refresh_blocked,
    register_refresh_failure,
)
from ..services.auth_signin_audit import record_auth_signin_event
from ..services.oauth_exchange import OAuthExchangeError, exchange_google_authorization_code, exchange_yandex_authorization_code
from ..services.oauth_user import link_oauth_identity_to_user, upsert_user_from_oauth_profile
from ..services.service_refresh_token import issue_refresh_token, rotate_refresh_token
from .dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class ExtensionAuthUrlResponse(BaseModel):
    auth_url: str


class ExtensionFinalizeResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: dict


class AuthRefreshRequest(BaseModel):
    refresh_token: str


class AuthRefreshResponse(BaseModel):
    access_token: str
    refresh_token: str


def _is_allowed_extension_redirect(url: str) -> bool:
    from urllib.parse import urlparse

    u = urlparse((url or "").strip())
    return bool(u.scheme == "https" and u.netloc.endswith(".chromiumapp.org"))


def _web_oauth_callback_uri(provider: str) -> str:
    return f"{oauth_public_api_origin()}/api/auth/{provider}/callback"


def _web_link_callback_uri(provider: str) -> str:
    return f"{oauth_public_api_origin()}/api/auth/{provider}/link/callback"


def _google_web_login_authorize_url(
    *,
    client: str | None,
    next_url: str | None,
    prompt: str | None,
) -> str:
    """Same authorize URL as Web UI GET /google (redirect_uri = server /callback)."""
    cb = _web_oauth_callback_uri("google")
    state = mint_web_oauth_state(provider="google", client=client, next_url=next_url)
    params = {
        "client_id": app_config.auth.google.client_id,
        "redirect_uri": cb,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    }
    if prompt:
        params["prompt"] = prompt
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params, quote_via=quote)


def _yandex_web_login_authorize_url(
    *,
    client: str | None,
    next_url: str | None,
    force_confirm: bool,
) -> str:
    """Same authorize URL shape as Web UI GET /yandex (redirect_uri = server /callback)."""
    cb = _web_oauth_callback_uri("yandex")
    state = mint_web_oauth_state(provider="yandex", client=client, next_url=next_url)
    params = {
        "client_id": app_config.auth.yandex.client_id,
        "redirect_uri": cb,
        "response_type": "code",
        "state": state,
    }
    if force_confirm:
        params["force_confirm"] = "yes"
    return "https://oauth.yandex.ru/authorize?" + urlencode(params, quote_via=quote)


def _redirect_web_settings_after_link(
    *,
    success: bool,
    provider: str | None = None,
    reason: str | None = None,
) -> RedirectResponse:
    webui = os.environ.get("VT_WEBUI_ORIGIN", "http://localhost:3002").strip().rstrip("/")
    if success:
        q = urlencode({"oauth_link": "success", "provider": provider or ""})
        return RedirectResponse(url=f"{webui}/settings?{q}", status_code=status.HTTP_302_FOUND)
    q = urlencode({"oauth_link": "error", "reason": reason or "unknown"})
    return RedirectResponse(url=f"{webui}/settings?{q}", status_code=status.HTTP_302_FOUND)


def _oauth_redirect_to_webui(access_token: str, refresh_token: str) -> RedirectResponse:
    """Send the browser back to the SPA with access + refresh tokens in the URL fragment (C7.2)."""
    webui = os.environ.get("VT_WEBUI_ORIGIN", "http://localhost:3002").strip().rstrip("/")
    frag = (
        f"access_token={quote(access_token, safe='')}&refresh_token={quote(refresh_token, safe='')}"
    )
    return RedirectResponse(
        url=f"{webui}/login#{frag}",
        status_code=status.HTTP_302_FOUND,
    )


def _oauth_redirect_to_admin_landing(landing_base: str, access_token: str, refresh_token: str) -> RedirectResponse:
    """Ops admin-webui: same fragment contract as Web UI, but landing origin is allowlisted (VT_ADMIN_WEBUI_*)."""
    base = (landing_base or "").strip().rstrip("/")
    frag = (
        f"access_token={quote(access_token, safe='')}&refresh_token={quote(refresh_token, safe='')}"
    )
    return RedirectResponse(url=f"{base}/#{frag}", status_code=status.HTTP_302_FOUND)


def _oauth_redirect_to_extension(access_token: str, refresh_token: str, next_url: str) -> RedirectResponse:
    """
    Send the browser back to the browser-extension web auth flow.

    `chrome.identity.launchWebAuthFlow` expects the final redirect to land on a
    URL under `https://<extension-id>.chromiumapp.org/*`.
    """
    from urllib.parse import urlparse

    u = urlparse((next_url or "").strip())
    if not (u.scheme == "https" and u.netloc.endswith(".chromiumapp.org")):
        return _oauth_redirect_to_webui(access_token, refresh_token)

    sep = "&" if ("#" in next_url) else "#"
    frag = (
        f"access_token={quote(access_token, safe='')}&refresh_token={quote(refresh_token, safe='')}"
    )
    return RedirectResponse(
        url=f"{next_url}{sep}{frag}",
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
    client_ip: str | None = None,
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
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_web",
            reason_code="token_exchange",
            provider=provider,
            client_fingerprint=client_fingerprint(client_ip),
        )
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    user = upsert_user_from_oauth_profile(db, provider=provider, profile=profile)
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_plain = issue_refresh_token(db, user_id=user.id)
    record_auth_signin_event(
        outcome="success",
        channel="oauth_web",
        reason_code=None,
        provider=provider,
        user_id=user.id,
        client_fingerprint=client_fingerprint(client_ip),
    )
    if (client or "").strip().lower() == "extension" and next_url:
        return _oauth_redirect_to_extension(access_token, refresh_plain, next_url)
    if (client or "").strip().lower() == "admin":
        if not is_allowed_admin_oauth_next(next_url):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid admin OAuth landing URL (configure VT_ADMIN_WEBUI_ORIGIN or VT_ADMIN_WEBUI_ORIGINS)",
            )
        return _oauth_redirect_to_admin_landing((next_url or "").strip(), access_token, refresh_plain)
    return _oauth_redirect_to_webui(access_token, refresh_plain)


async def _finalize_extension_json(
    db: Session,
    *,
    provider: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client_ip: str | None = None,
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
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_extension",
            reason_code="token_exchange",
            provider=provider,
            client_fingerprint=client_fingerprint(client_ip),
        )
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    user = upsert_user_from_oauth_profile(db, provider=provider, profile=profile)
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_plain = issue_refresh_token(db, user_id=user.id)
    record_auth_signin_event(
        outcome="success",
        channel="oauth_extension",
        reason_code=None,
        provider=provider,
        user_id=user.id,
        client_fingerprint=client_fingerprint(client_ip),
    )
    return ExtensionFinalizeResponse(
        access_token=access_token,
        refresh_token=refresh_plain,
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


@router.post("/refresh", response_model=AuthRefreshResponse)
async def auth_refresh(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    body: AuthRefreshRequest,
):
    """Mint a new access JWT and rotated refresh token (C7.2)."""
    ip = client_ip_from_request(request)
    fp = client_fingerprint(ip)
    ra = int(app_config.auth.lockout.block_seconds)
    if is_refresh_blocked(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed refresh attempts; try again later",
            headers={"Retry-After": str(ra)},
        )
    raw = body.refresh_token.strip()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing refresh_token")
    try:
        user, new_refresh = rotate_refresh_token(db, plaintext=raw)
    except ValueError:
        now_blocked = register_refresh_failure(ip)
        record_auth_signin_event(
            outcome="failure",
            channel="refresh",
            reason_code="invalid_refresh",
            client_fingerprint=fp,
        )
        if now_blocked or is_refresh_blocked(ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed refresh attempts; try again later",
                headers={"Retry-After": str(ra)},
            ) from None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from None
    clear_refresh_failures(ip)
    record_auth_signin_event(
        outcome="success",
        channel="refresh",
        reason_code=None,
        user_id=user.id,
        client_fingerprint=fp,
    )
    access_token = create_access_token(data={"sub": str(user.id)})
    return AuthRefreshResponse(access_token=access_token, refresh_token=new_refresh)


@router.get("/me")
async def auth_me(current_user: Annotated[User, Depends(get_current_user)]):
    """Return the authenticated user (Bearer JWT)."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.display_name,
        "provider": current_user.auth_provider,
    }


@router.get("/google/link/start", response_model=ExtensionAuthUrlResponse)
async def google_oauth_link_start(current_user: Annotated[User, Depends(get_current_user)]):
    """Start OAuth to attach a Google identity to the logged-in VT user (C7.4)."""
    cb = _web_link_callback_uri("google")
    state = mint_web_link_oauth_state(user_id=str(current_user.id), provider="google")
    params = {
        "client_id": app_config.auth.google.client_id,
        "redirect_uri": cb,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account consent",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params, quote_via=quote)
    return ExtensionAuthUrlResponse(auth_url=auth_url)


@router.get("/google/link/callback")
async def google_oauth_link_callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    ip = client_ip_from_request(request)
    fp = client_fingerprint(ip)
    if error and not code:
        logger.warning("Google link callback error: %s", error_description or error)
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="provider_denied",
            provider="google",
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="provider_denied")
    if not code or not state:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="missing_code",
            provider="google",
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="missing_code")
    try:
        payload = parse_web_link_oauth_state(state)
    except ValueError:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="invalid_state",
            provider="google",
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="invalid_state")
    if payload.get("provider") != "google":
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="state_mismatch",
            provider="google",
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="state_mismatch")
    try:
        uid = UUID(str(payload.get("uid")))
    except ValueError:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="invalid_uid",
            provider="google",
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="invalid_state")
    cb = _web_link_callback_uri("google")
    try:
        profile = await exchange_google_authorization_code(code=code, redirect_uri=cb, code_verifier=None)
    except OAuthExchangeError:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="token_exchange",
            provider="google",
            user_id=uid,
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="token_exchange")
    try:
        link_oauth_identity_to_user(db, target_user_id=uid, provider="google", profile=profile)
    except HTTPException as e:
        if e.status_code == status.HTTP_409_CONFLICT:
            record_auth_signin_event(
                outcome="failure",
                channel="oauth_link",
                reason_code="conflict",
                provider="google",
                user_id=uid,
                client_fingerprint=fp,
            )
            return _redirect_web_settings_after_link(success=False, reason=str(e.detail))
        if e.status_code == status.HTTP_404_NOT_FOUND:
            record_auth_signin_event(
                outcome="failure",
                channel="oauth_link",
                reason_code="user_not_found",
                provider="google",
                user_id=uid,
                client_fingerprint=fp,
            )
            return _redirect_web_settings_after_link(success=False, reason="user_not_found")
        raise
    record_auth_signin_event(
        outcome="success",
        channel="oauth_link",
        reason_code=None,
        provider="google",
        user_id=uid,
        client_fingerprint=fp,
    )
    return _redirect_web_settings_after_link(success=True, provider="google")


@router.get("/yandex/link/start", response_model=ExtensionAuthUrlResponse)
async def yandex_oauth_link_start(current_user: Annotated[User, Depends(get_current_user)]):
    cb = _web_link_callback_uri("yandex")
    state = mint_web_link_oauth_state(user_id=str(current_user.id), provider="yandex")
    params = {
        "client_id": app_config.auth.yandex.client_id,
        "redirect_uri": cb,
        "response_type": "code",
        "state": state,
        "force_confirm": "yes",
    }
    auth_url = "https://oauth.yandex.ru/authorize?" + urlencode(params, quote_via=quote)
    return ExtensionAuthUrlResponse(auth_url=auth_url)


@router.get("/yandex/link/callback")
async def yandex_oauth_link_callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    ip = client_ip_from_request(request)
    fp = client_fingerprint(ip)
    if error and not code:
        logger.warning("Yandex link callback error: %s", error_description or error)
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="provider_denied",
            provider="yandex",
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="provider_denied")
    if not code or not state:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="missing_code",
            provider="yandex",
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="missing_code")
    try:
        payload = parse_web_link_oauth_state(state)
    except ValueError:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="invalid_state",
            provider="yandex",
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="invalid_state")
    if payload.get("provider") != "yandex":
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="state_mismatch",
            provider="yandex",
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="state_mismatch")
    try:
        uid = UUID(str(payload.get("uid")))
    except ValueError:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="invalid_uid",
            provider="yandex",
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="invalid_state")
    cb = _web_link_callback_uri("yandex")
    try:
        profile = await exchange_yandex_authorization_code(code=code, redirect_uri=cb, code_verifier=None)
    except OAuthExchangeError:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_link",
            reason_code="token_exchange",
            provider="yandex",
            user_id=uid,
            client_fingerprint=fp,
        )
        return _redirect_web_settings_after_link(success=False, reason="token_exchange")
    try:
        link_oauth_identity_to_user(db, target_user_id=uid, provider="yandex", profile=profile)
    except HTTPException as e:
        if e.status_code == status.HTTP_409_CONFLICT:
            record_auth_signin_event(
                outcome="failure",
                channel="oauth_link",
                reason_code="conflict",
                provider="yandex",
                user_id=uid,
                client_fingerprint=fp,
            )
            return _redirect_web_settings_after_link(success=False, reason=str(e.detail))
        if e.status_code == status.HTTP_404_NOT_FOUND:
            record_auth_signin_event(
                outcome="failure",
                channel="oauth_link",
                reason_code="user_not_found",
                provider="yandex",
                user_id=uid,
                client_fingerprint=fp,
            )
            return _redirect_web_settings_after_link(success=False, reason="user_not_found")
        raise
    record_auth_signin_event(
        outcome="success",
        channel="oauth_link",
        reason_code=None,
        provider="yandex",
        user_id=uid,
        client_fingerprint=fp,
    )
    return _redirect_web_settings_after_link(success=True, provider="yandex")


@router.get("/google")
async def google_oauth_start(
    client: str | None = None,
    next: str | None = None,  # noqa: A002
):
    """Initiate Google OAuth flow."""
    if (client or "").strip().lower() == "admin" and not is_allowed_admin_oauth_next(next):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin OAuth requires VT_ADMIN_WEBUI_ORIGIN(S) and a matching next URL",
        )
    google_auth_url = _google_web_login_authorize_url(client=client, next_url=next, prompt=None)
    return RedirectResponse(url=google_auth_url)


@router.get("/google/extension/authorize-url", response_model=ExtensionAuthUrlResponse)
async def google_extension_web_aligned_authorize_url(
    client: str | None = Query("extension"),
    next: str = Query(..., description="chrome.identity.getRedirectURL(...)"),
):
    """
    JSON authorize URL for MV3 extension: same OAuth as Web UI (server callback), without a localhost
    redirect hop inside chrome.identity.launchWebAuthFlow (popup fetches this first, then opens provider).
    """
    nxt = (next or "").strip()
    if not _is_allowed_extension_redirect(nxt):
        raise HTTPException(status_code=400, detail="Invalid extension redirect URL (next)")
    auth_url = _google_web_login_authorize_url(
        client=client,
        next_url=nxt,
        prompt="select_account",
    )
    return ExtensionAuthUrlResponse(auth_url=auth_url)


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
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    ip = client_ip_from_request(request)
    fp = client_fingerprint(ip)
    if error and not code:
        msg = error_description or error
        logger.warning("Google OAuth callback error: %s", msg)
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_web",
            reason_code="provider_error",
            provider="google",
            client_fingerprint=fp,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"OAuth provider error: {msg}")
    if not code:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_web",
            reason_code="missing_code",
            provider="google",
            client_fingerprint=fp,
        )
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
        client_ip=ip,
    )


@router.post("/google/extension/finalize", response_model=ExtensionFinalizeResponse)
async def google_extension_finalize(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str = Query(...),
    code_verifier: str = Query(..., min_length=43, max_length=128),
    state: str = Query(...),
):
    ip = client_ip_from_request(request)
    fp = client_fingerprint(ip)
    try:
        payload = parse_extension_oauth_state(state)
    except ValueError:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_extension",
            reason_code="invalid_state",
            provider="google",
            client_fingerprint=fp,
        )
        raise HTTPException(status_code=400, detail="Invalid or expired state") from None
    if payload.get("provider") != "google":
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_extension",
            reason_code="state_provider_mismatch",
            provider="google",
            client_fingerprint=fp,
        )
        raise HTTPException(status_code=400, detail="state provider mismatch")
    redirect_uri = (payload.get("ru") or "").strip()
    if not redirect_uri or not _is_allowed_extension_redirect(redirect_uri):
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_extension",
            reason_code="invalid_redirect_uri",
            provider="google",
            client_fingerprint=fp,
        )
        raise HTTPException(status_code=400, detail="Invalid redirect_uri in state")

    return await _finalize_extension_json(
        db,
        provider="google",
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier.strip(),
        client_ip=ip,
    )


@router.get("/yandex")
async def yandex_oauth_start(
    client: str | None = None,
    next: str | None = None,  # noqa: A002
):
    """Initiate Yandex OAuth flow."""
    if (client or "").strip().lower() == "admin" and not is_allowed_admin_oauth_next(next):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin OAuth requires VT_ADMIN_WEBUI_ORIGIN(S) and a matching next URL",
        )
    yandex_auth_url = _yandex_web_login_authorize_url(
        client=client,
        next_url=next,
        force_confirm=True,
    )
    return RedirectResponse(url=yandex_auth_url)


@router.get("/yandex/extension/authorize-url", response_model=ExtensionAuthUrlResponse)
async def yandex_extension_web_aligned_authorize_url(
    client: str | None = Query("extension"),
    next: str = Query(..., description="chrome.identity.getRedirectURL(...)"),
):
    """Same as GET /yandex for extension: JSON authorize URL; force_confirm so account/consent UI appears."""
    nxt = (next or "").strip()
    if not _is_allowed_extension_redirect(nxt):
        raise HTTPException(status_code=400, detail="Invalid extension redirect URL (next)")
    auth_url = _yandex_web_login_authorize_url(
        client=client,
        next_url=nxt,
        force_confirm=True,
    )
    return ExtensionAuthUrlResponse(auth_url=auth_url)


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
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    ip = client_ip_from_request(request)
    fp = client_fingerprint(ip)
    if error and not code:
        msg = error_description or error
        logger.warning("Yandex OAuth callback error: %s", msg)
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_web",
            reason_code="provider_error",
            provider="yandex",
            client_fingerprint=fp,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"OAuth provider error: {msg}")
    if not code:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_web",
            reason_code="missing_code",
            provider="yandex",
            client_fingerprint=fp,
        )
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
        client_ip=ip,
    )


@router.post("/yandex/extension/finalize", response_model=ExtensionFinalizeResponse)
async def yandex_extension_finalize(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str = Query(...),
    code_verifier: str = Query(..., min_length=43, max_length=128),
    state: str = Query(...),
):
    ip = client_ip_from_request(request)
    fp = client_fingerprint(ip)
    try:
        payload = parse_extension_oauth_state(state)
    except ValueError:
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_extension",
            reason_code="invalid_state",
            provider="yandex",
            client_fingerprint=fp,
        )
        raise HTTPException(status_code=400, detail="Invalid or expired state") from None
    if payload.get("provider") != "yandex":
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_extension",
            reason_code="state_provider_mismatch",
            provider="yandex",
            client_fingerprint=fp,
        )
        raise HTTPException(status_code=400, detail="state provider mismatch")
    redirect_uri = (payload.get("ru") or "").strip()
    if not redirect_uri or not _is_allowed_extension_redirect(redirect_uri):
        record_auth_signin_event(
            outcome="failure",
            channel="oauth_extension",
            reason_code="invalid_redirect_uri",
            provider="yandex",
            client_fingerprint=fp,
        )
        raise HTTPException(status_code=400, detail="Invalid redirect_uri in state")

    return await _finalize_extension_json(
        db,
        provider="yandex",
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier.strip(),
        client_ip=ip,
    )
