"""Signed OAuth `state` JWTs for extension PKCE flow and Web UI redirect hints (C7.3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from .security import JWT_ALGORITHM, JWT_SECRET_KEY

STATE_TTL_MINUTES = 15
TYP_EXTENSION = "vt_oauth_ext"
TYP_WEB = "vt_oauth_web"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def mint_extension_oauth_state(
    *,
    provider: str,
    redirect_uri: str,
    ux_mode: str,
    account_prompt: str,
) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "oauth_typ": TYP_EXTENSION,
        "provider": provider,
        "ru": redirect_uri,
        "ux": ux_mode,
        "ap": account_prompt,
        "iat": now,
        "exp": now + timedelta(minutes=STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def parse_extension_oauth_state(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        raise ValueError("invalid_state") from e
    if payload.get("oauth_typ") != TYP_EXTENSION:
        raise ValueError("invalid_state_type")
    return payload


def mint_web_oauth_state(
    *,
    provider: str,
    client: str | None,
    next_url: str | None,
) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "oauth_typ": TYP_WEB,
        "provider": provider,
        "client": (client or "").strip(),
        "next": (next_url or "").strip(),
        "iat": now,
        "exp": now + timedelta(minutes=STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def parse_web_oauth_state(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        raise ValueError("invalid_state") from e
    if payload.get("oauth_typ") != TYP_WEB:
        raise ValueError("invalid_state_type")
    return payload
