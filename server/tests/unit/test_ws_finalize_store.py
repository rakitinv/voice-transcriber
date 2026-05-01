"""Идемпотентность finalize_id (Redis при наличии VT_REDIS_URL)."""

from __future__ import annotations

import os
import uuid

import pytest

from app.api.ws_finalize_store import (
    mark_finalize_done,
    release_finalize_pending,
    try_claim_finalize_pending,
)


@pytest.fixture()
def redis_url():
    url = os.environ.get("VT_REDIS_URL", "").strip()
    if not url:
        pytest.skip("VT_REDIS_URL not set — Redis-backed finalize dedup not tested")
    return url


def test_claim_finalize_idempotent_twice(monkeypatch, redis_url):
    monkeypatch.setenv("VT_REDIS_URL", redis_url)
    cid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    key_ns = f"vt:ws:finalize:{cid}:{fid}"
    try:
        import redis as redis_sync

        r = redis_sync.Redis.from_url(redis_url)
        r.delete(key_ns)
        assert try_claim_finalize_pending(cid, fid) in ("claimed", "no_redis")
        assert try_claim_finalize_pending(cid, fid) == "duplicate"
        mark_finalize_done(cid, fid)
        assert try_claim_finalize_pending(cid, fid) == "duplicate"
    finally:
        try:
            r.delete(key_ns)
        except Exception:
            pass


def test_claim_without_redis_always_true(monkeypatch):
    monkeypatch.delenv("VT_REDIS_URL", raising=False)
    assert try_claim_finalize_pending("c", "f") == "no_redis"
    assert try_claim_finalize_pending("c", "f") == "no_redis"


def test_release_allows_retry(monkeypatch, redis_url):
    monkeypatch.setenv("VT_REDIS_URL", redis_url)
    cid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    assert try_claim_finalize_pending(cid, fid) in ("claimed", "no_redis")
    # Release should allow re-claim.
    release_finalize_pending(cid, fid)
    assert try_claim_finalize_pending(cid, fid) in ("claimed", "no_redis")
