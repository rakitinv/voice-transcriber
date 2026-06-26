"""Append-only pipeline_events for Ops console (§9 — no transcript text)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import PipelineEvent

_ALLOWED_EVENT_TYPES = frozenset(
    {
        "asr_started",
        "asr_completed",
        "asr_failed",
        "diarization_started",
        "diarization_completed",
        "diarization_failed",
        "embedding_indexed",
        "summary_started",
        "summary_completed",
        "summary_failed",
    }
)

_ALLOWED_DETAIL_KEYS = frozenset(
    {
        "transcript_id",
        "source_transcript_id",
        "revision",
        "reason_code",
        "error_hint",
        "exception_type",
        "chunks_total",
        "chunks_completed",
    }
)


def _sanitize_detail(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    if detail is None:
        return None
    if not isinstance(detail, dict):
        return None
    out: dict[str, Any] = {}
    for k, v in detail.items():
        if str(k) not in _ALLOWED_DETAIL_KEYS:
            continue
        if k in ("transcript_id", "source_transcript_id", "revision", "chunks_total", "chunks_completed"):
            if isinstance(v, bool) or v is None:
                continue
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                continue
            continue
        if k == "reason_code" and isinstance(v, str):
            s = v.strip()
            if s:
                out[k] = s[:128]
            continue
        if k == "error_hint" and isinstance(v, str):
            s = v.strip()
            if s:
                out[k] = s[:500]
            continue
        if k == "exception_type" and isinstance(v, str):
            s = v.strip()
            if s:
                out[k] = s[:64]
    return out or None


def record_pipeline_event(
    db: Session,
    *,
    conversation_id: UUID,
    event_type: str,
    transcript_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    if event_type not in _ALLOWED_EVENT_TYPES:
        return
    row = PipelineEvent(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        event_type=event_type,
        transcript_id=int(transcript_id) if transcript_id is not None else None,
        detail=_sanitize_detail(detail),
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
