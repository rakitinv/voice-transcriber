"""Unit tests for realtime fast snapshot persist and upload idempotency."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

_mock_s3 = MagicMock()
_mock_s3.storage = MagicMock()
sys.modules.setdefault("core.s3", _mock_s3)

from app.api.realtime_finalize import persist_fast_snapshot  # noqa: E402
from app.api.upload import _final_transcript_already_queued  # noqa: E402


def test_persist_fast_snapshot_upsert(monkeypatch):
    conv_id = uuid4()
    user_id = uuid4()
    fast_row = MagicMock()
    fast_row.id = 42
    fast_row.meta = {"processing_tier": "fast", "source": "realtime"}

    class FakeSession:
        def query(self, model):
            return self

        def filter(self, *args, **kwargs):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return MagicMock(id=conv_id, active_transcript_id=None)

        def order_by(self, *args):
            return self

        def all(self):
            return [fast_row]

        def flush(self):
            return None

        def add(self, row):
            return None

    fake_db = FakeSession()

    def session_scope():
        class _Ctx:
            def __enter__(self):
                return fake_db

            def __exit__(self, *args):
                return False

        return _Ctx()

    uploads: list[str] = []

    monkeypatch.setattr("app.api.realtime_finalize.session_scope", session_scope)
    monkeypatch.setattr(
        "app.api.realtime_finalize._has_non_fast_final_row", lambda *a, **k: False
    )
    monkeypatch.setattr(
        "app.api.realtime_finalize.storage.upload_transcript_json",
        lambda *a, **k: uploads.append("json"),
    )
    monkeypatch.setattr(
        "app.api.realtime_finalize.storage.upload_transcript_markdown",
        lambda *a, **k: uploads.append("md"),
    )

    ok = persist_fast_snapshot(
        user_id=str(user_id),
        conversation_id=str(conv_id),
        partial_texts=[{"start": 0.0, "end": 2.0, "text": "hello"}],
        pcm_len=32000 * 3,
        snapshot_seq=1,
        step_s=2.0,
        overlap_s=1.0,
    )
    assert ok is True
    assert fast_row.meta["fast_snapshot_seq"] == 1
    assert uploads == ["json", "md"]


def test_final_transcript_already_queued_skips_fast_only():
    db = MagicMock()
    conv_id = uuid4()
    user_id = uuid4()

    fast_only = MagicMock(meta={"processing_tier": "fast"})
    db.query.return_value.filter.return_value.all.return_value = [fast_only]
    assert _final_transcript_already_queued(db, conv_id, user_id) is False

    with_final = MagicMock(meta={"processing_tier": "final"})
    db.query.return_value.filter.return_value.all.return_value = [fast_only, with_final]
    assert _final_transcript_already_queued(db, conv_id, user_id) is True
