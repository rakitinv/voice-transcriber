"""Public base URL for OAuth redirect_uri (Web UI callback must match Google/Yandex console)."""

from __future__ import annotations

import os

from .config import app_config


def oauth_public_api_origin() -> str:
    """
    Origin where `/api/auth/*/callback` is reachable (scheme + host[:port], no path, no trailing slash).

    Set **VT_PUBLIC_API_URL** in Docker/production when the API is behind another host/port than `server.yaml`.
    """
    raw = (os.environ.get("VT_PUBLIC_API_URL") or "").strip().rstrip("/")
    if raw:
        return raw
    host = (os.environ.get("VT_PUBLIC_API_HOST") or "127.0.0.1").strip()
    return f"http://{host}:{app_config.port}"
