"""Persist speaker display names on active diarized transcript (C1.4)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Conversation, Transcript
from core.speaker_labels import (
    apply_speaker_labels,
    rebuild_transcript_md,
)
from workers.tasks.embeddings import schedule_transcript_embedding


def active_diarized_transcript(
    db: Session, conversation: Conversation
) -> Transcript | None:
    if conversation.active_transcript_id is not None:
        row = (
            db.query(Transcript)
            .filter(
                Transcript.id == conversation.active_transcript_id,
                Transcript.conversation_id == conversation.id,
                Transcript.user_id == conversation.user_id,
                Transcript.status == "success",
                Transcript.kind == "asr_diarized",
            )
            .first()
        )
        if row is not None:
            return row
    return (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation.id,
            Transcript.user_id == conversation.user_id,
            Transcript.kind == "asr_diarized",
            Transcript.status == "success",
        )
        .order_by(Transcript.revision.desc())
        .first()
    )


def persist_labels_on_transcript(
    db: Session,
    conversation: Conversation,
    transcript_row: Transcript,
    *,
    reindex_embedding: bool = False,
) -> None:
    """Apply conversation.speaker_labels to transcript json/md in DB."""
    tjson = dict(transcript_row.transcript_json or {"segments": []})
    raw_segments = tjson.get("segments") or []
    if not isinstance(raw_segments, list):
        raw_segments = []
    labels = (
        conversation.speaker_labels
        if isinstance(conversation.speaker_labels, dict)
        else None
    )
    segments = apply_speaker_labels(
        [s for s in raw_segments if isinstance(s, dict)],
        labels,
    )
    tjson["segments"] = segments
    transcript_row.transcript_json = tjson
    transcript_row.transcript_md = rebuild_transcript_md(segments)
    if reindex_embedding:
        schedule_transcript_embedding(int(transcript_row.id))


def reset_speaker_labels_on_diarization_rerun(conversation: Conversation) -> None:
    """v1: clear custom names when diarization produces a new revision."""
    conversation.speaker_labels = None
    conversation.speaker_identification_status = "idle"


def conversation_for_user(
    db: Session, conversation_id: UUID, user_id: UUID
) -> Conversation | None:
    return (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )


def merge_speaker_label_maps(
    existing: dict[str, Any] | None, updates: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    merged = dict(existing) if isinstance(existing, dict) else {}
    for sid, entry in updates.items():
        if isinstance(entry, dict):
            merged[str(sid)] = entry
    return merged
