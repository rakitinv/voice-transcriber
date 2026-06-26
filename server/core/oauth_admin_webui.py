"""Allowlist for Ops admin-webui OAuth return URL (fragment tokens after server callback)."""

from __future__ import annotations

import os
from urllib.parse import urlparse


def _normalize_origin(url: str) -> str | None:
    u = urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    # Ignore path for allowlist match (landing is always origin + #fragment).
    return f"{u.scheme}://{u.netloc}".rstrip("/").lower()


def allowed_admin_oauth_origins() -> frozenset[str]:
    """
    Origins permitted for ``client=admin`` + ``next=`` on ``GET /api/auth/{google|yandex}``.

    Set ``VT_ADMIN_WEBUI_ORIGINS`` (comma-separated) or a single ``VT_ADMIN_WEBUI_ORIGIN``.
    If unset, admin OAuth landing is disabled (fail closed).
    """
    raw = (os.environ.get("VT_ADMIN_WEBUI_ORIGINS") or os.environ.get("VT_ADMIN_WEBUI_ORIGIN") or "").strip()
    if not raw:
        return frozenset()
    out: set[str] = set()
    for part in raw.split(","):
        o = _normalize_origin(part)
        if o:
            out.add(o)
    return frozenset(out)


def is_allowed_admin_oauth_next(next_url: str | None) -> bool:
    if not (next_url or "").strip():
        return False
    cand = _normalize_origin(next_url)
    if not cand:
        return False
    return cand in allowed_admin_oauth_origins()


def _admin_landing_candidates_from_env() -> list[str]:
    """Full landing bases from env (may include path, e.g. ``https://host/admin``)."""
    raw = (os.environ.get("VT_ADMIN_WEBUI_ORIGINS") or os.environ.get("VT_ADMIN_WEBUI_ORIGIN") or "").strip()
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        u = (part or "").strip().rstrip("/")
        if not u:
            continue
        parsed = urlparse(u)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            out.append(u)
    return out


def resolve_admin_oauth_landing_url(next_url: str) -> str:
    """
    Canonical admin SPA base URL (no fragment, no trailing slash) after OAuth.

    If ``next`` is only an origin (``https://host``), append the path from
    ``VT_ADMIN_WEBUI_ORIGIN(S)`` when configured (e.g. ``/admin``).
    """
    raw = (next_url or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return raw
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = (parsed.path or "").rstrip("/")
    if path:
        return f"{origin}{path}"
    for candidate in _admin_landing_candidates_from_env():
        cp = urlparse(candidate)
        cand_origin = f"{cp.scheme}://{cp.netloc}".rstrip("/").lower()
        if cand_origin != origin.lower():
            continue
        cpath = (cp.path or "").rstrip("/")
        if cpath:
            return f"{origin}{cpath}"
    return origin
