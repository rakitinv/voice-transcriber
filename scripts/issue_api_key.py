#!/usr/bin/env python3
"""Insert a UserApiKey row and print the secret once (Phase C6).

Usage (from repository root, with DB reachable as in configs/server.yaml):

  cd server && poetry run python ../scripts/issue_api_key.py user@example.com "CLI laptop"

Requires applied migration ``c6_api_keys_001`` (user_api_keys table).
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SERVER = _REPO / "server"
sys.path.insert(0, str(_SERVER))

from app.models import User, UserApiKey  # noqa: E402
from core.db import SessionLocal  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Issue API key for Voice Transcriber user")
    p.add_argument("email", help="User email (existing row in users)")
    p.add_argument("label", nargs="?", default=None, help="Optional label stored in DB")
    args = p.parse_args()

    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email.strip()).first()
        if user is None:
            print(f"No user with email: {args.email!r}", file=sys.stderr)
            return 1
        row = UserApiKey(user_id=user.id, key_hash=digest, label=args.label)
        db.add(row)
        db.commit()
    finally:
        db.close()

    print("Save this secret now; it cannot be retrieved later:", file=sys.stderr)
    print(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
