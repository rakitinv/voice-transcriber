"""HTTP client metadata for auth lockout and sign-in audit (no raw IP persisted by default)."""

from __future__ import annotations

import hashlib
import os

from fastapi import Request


def client_ip_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    xf = (request.headers.get("x-forwarded-for") or "").strip()
    if xf:
        return xf.split(",")[0].strip() or None
    if request.client and request.client.host:
        return str(request.client.host).strip() or None
    return None


def client_fingerprint(ip: str | None) -> str | None:
    if not ip:
        return None
    salt = (os.environ.get("VT_AUTH_AUDIT_SALT") or "dev-only-salt-change-in-prod").encode()
    return hashlib.sha256(salt + b"|" + ip.encode("utf-8", errors="replace")).hexdigest()
