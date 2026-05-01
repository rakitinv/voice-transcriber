"""JWT from env / flags (same rules as Web UI and phase_a_upload_smoke)."""

from __future__ import annotations

from urllib.parse import unquote


def normalize_access_token(raw: str) -> str:
    t = raw.strip().strip('"').strip("'")
    if "#access_token=" in t:
        t = t.split("#access_token=", 1)[1]
    if "access_token=" in t and not t.startswith("eyJ"):
        t = t.split("access_token=", 1)[1]
    t = t.split("&", 1)[0].split("#", 1)[0]
    return unquote(t)


def looks_like_jwt(token: str) -> bool:
    parts = [p for p in token.split(".") if p]
    return len(parts) == 3
