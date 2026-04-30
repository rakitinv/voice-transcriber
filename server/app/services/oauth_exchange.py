"""Exchange OAuth authorization codes with Google/Yandex (httpx async)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from core.config import app_config
from core.logging import logger

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
YANDEX_TOKEN_URL = "https://oauth.yandex.ru/token"
YANDEX_USERINFO_URL = "https://login.yandex.ru/info"


@dataclass
class OAuthProfile:
    subject: str
    email: str
    display_name: str | None


class OAuthExchangeError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


async def exchange_google_authorization_code(
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str | None,
) -> OAuthProfile:
    cfg = app_config.auth.google
    data: dict[str, str] = {
        "code": code,
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if code_verifier:
        data["code_verifier"] = code_verifier

    async with httpx.AsyncClient(timeout=25.0) as client:
        tr = await client.post(GOOGLE_TOKEN_URL, data=data)
        if tr.status_code != 200:
            logger.warning("Google token exchange failed: %s %s", tr.status_code, tr.text[:500])
            raise OAuthExchangeError("Google token exchange failed", status_code=400)
        token_json = tr.json()
        access_token = token_json.get("access_token")
        if not access_token:
            raise OAuthExchangeError("Google token response missing access_token", status_code=400)

        ui = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if ui.status_code != 200:
            logger.warning("Google userinfo failed: %s %s", ui.status_code, ui.text[:500])
            raise OAuthExchangeError("Google userinfo failed", status_code=400)
        j = ui.json()
        sub = j.get("sub")
        if not sub:
            raise OAuthExchangeError("Google userinfo missing sub", status_code=400)
        email = (j.get("email") or "").strip()
        if not email:
            email = f"google.{sub}@oauth.placeholder.local"
        name = j.get("name")
        dn = name.strip() if isinstance(name, str) and name.strip() else None
        return OAuthProfile(subject=str(sub), email=email, display_name=dn)


async def exchange_yandex_authorization_code(
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str | None,
) -> OAuthProfile:
    cfg = app_config.auth.yandex
    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        data["code_verifier"] = code_verifier

    async with httpx.AsyncClient(timeout=25.0) as client:
        tr = await client.post(YANDEX_TOKEN_URL, data=data)
        if tr.status_code != 200:
            logger.warning("Yandex token exchange failed: %s %s", tr.status_code, tr.text[:500])
            raise OAuthExchangeError("Yandex token exchange failed", status_code=400)
        token_json = tr.json()
        access_token = token_json.get("access_token")
        if not access_token:
            raise OAuthExchangeError("Yandex token response missing access_token", status_code=400)

        ui = await client.get(
            YANDEX_USERINFO_URL,
            params={"format": "json"},
            headers={"Authorization": f"OAuth {access_token}"},
        )
        if ui.status_code != 200:
            logger.warning("Yandex userinfo failed: %s %s", ui.status_code, ui.text[:500])
            raise OAuthExchangeError("Yandex userinfo failed", status_code=400)
        j = ui.json()
        yid = j.get("id")
        if yid is None:
            raise OAuthExchangeError("Yandex userinfo missing id", status_code=400)
        subject = str(yid)
        login = (j.get("login") or "").strip()
        email = (j.get("default_email") or "").strip()
        if not email:
            safe_login = login or subject
            email = f"yandex.{safe_login}.id{subject}@oauth.placeholder.local"
        dn = j.get("display_name") or j.get("real_name")
        if isinstance(dn, str):
            dn = dn.strip() or None
        else:
            dn = None
        if not dn and login:
            dn = login
        return OAuthProfile(subject=subject, email=email, display_name=dn)
