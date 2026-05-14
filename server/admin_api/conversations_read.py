"""Read-only conversation queries for Admin API (technical fields only, §9)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, func
from sqlalchemy.orm import Session, aliased

from app.models import Conversation, Embedding, RecordingSessionSummary, Transcript, User


@dataclass(frozen=True)
class AdminConversationRow:
    conversation: Conversation
    active_transcript: Transcript | None
    recording_session_summary: RecordingSessionSummary | None
    transcript_count: int
    asr_chunk_completed: int | None = None
    asr_chunk_total: int | None = None


def fetch_busy_asr_chunk_progress(
    db: Session, conversation_ids: list[UUID]
) -> dict[UUID, tuple[int | None, int | None]]:
    """Latest pending/running ASR row per conversation: (completed, total)."""
    if not conversation_ids:
        return {}
    T = Transcript
    sub = (
        db.query(T.conversation_id, func.max(T.revision).label("max_rev"))
        .filter(
            T.conversation_id.in_(conversation_ids),
            T.kind == "asr",
            T.status.in_(("pending", "running")),
        )
        .group_by(T.conversation_id)
        .subquery()
    )
    rows = (
        db.query(T)
        .join(
            sub,
            and_(T.conversation_id == sub.c.conversation_id, T.revision == sub.c.max_rev),
        )
        .all()
    )
    out: dict[UUID, tuple[int | None, int | None]] = {}
    for t in rows:
        out[t.conversation_id] = (t.asr_chunk_completed, t.asr_chunk_total)
    return out


def _apply_admin_conversation_filters(
    q,
    *,
    At,
    Rss,
    user_id: UUID | None,
    transcript_status: str | None,
    transcript_kind: str | None,
    session_summary_status: str | None,
    session_summary_missing: bool | None,
    has_audio: bool | None,
    recording_session_id: UUID | None,
):
    q = q.filter(Conversation.deleted_at.is_(None))
    if user_id is not None:
        q = q.filter(Conversation.user_id == user_id)
    if transcript_status:
        q = q.filter(At.status == transcript_status)
    if transcript_kind:
        q = q.filter(At.kind == transcript_kind)
    if session_summary_status:
        q = q.filter(Rss.status == session_summary_status)
    if session_summary_missing is True:
        q = q.filter(Rss.recording_session_id.is_(None))
    elif session_summary_missing is False:
        q = q.filter(Rss.recording_session_id.isnot(None))
    if has_audio is True:
        q = q.filter(Conversation.audio_uploaded_at.isnot(None))
    elif has_audio is False:
        q = q.filter(Conversation.audio_uploaded_at.is_(None))
    if recording_session_id is not None:
        q = q.filter(Conversation.recording_session_id == recording_session_id)
    return q


def count_admin_conversations(
    db: Session,
    *,
    user_id: UUID | None,
    transcript_status: str | None,
    transcript_kind: str | None,
    session_summary_status: str | None = None,
    session_summary_missing: bool | None = None,
    has_audio: bool | None = None,
    recording_session_id: UUID | None = None,
) -> int:
    At = aliased(Transcript)
    Rss = aliased(RecordingSessionSummary)
    q = (
        db.query(func.count(func.distinct(Conversation.id)))
        .select_from(Conversation)
        .outerjoin(At, At.id == Conversation.active_transcript_id)
        .outerjoin(
            Rss,
            Rss.recording_session_id == Conversation.recording_session_id,
        )
    )
    q = _apply_admin_conversation_filters(
        q,
        At=At,
        Rss=Rss,
        user_id=user_id,
        transcript_status=transcript_status,
        transcript_kind=transcript_kind,
        session_summary_status=session_summary_status,
        session_summary_missing=session_summary_missing,
        has_audio=has_audio,
        recording_session_id=recording_session_id,
    )
    return int(q.scalar() or 0)


def _transcript_counts_for_conversations(db: Session, ids: list[UUID]) -> dict[UUID, int]:
    if not ids:
        return {}
    rows = (
        db.query(Transcript.conversation_id, func.count(Transcript.id))
        .filter(Transcript.conversation_id.in_(ids))
        .group_by(Transcript.conversation_id)
        .all()
    )
    return {cid: int(n) for cid, n in rows}


def list_admin_conversations(
    db: Session,
    *,
    user_id: UUID | None,
    transcript_status: str | None,
    transcript_kind: str | None,
    session_summary_status: str | None = None,
    session_summary_missing: bool | None = None,
    has_audio: bool | None = None,
    recording_session_id: UUID | None = None,
    limit: int,
    offset: int,
) -> list[AdminConversationRow]:
    At = aliased(Transcript)
    Rss = aliased(RecordingSessionSummary)
    q = (
        db.query(Conversation, At, Rss)
        .outerjoin(At, At.id == Conversation.active_transcript_id)
        .outerjoin(
            Rss,
            Rss.recording_session_id == Conversation.recording_session_id,
        )
    )
    q = _apply_admin_conversation_filters(
        q,
        At=At,
        Rss=Rss,
        user_id=user_id,
        transcript_status=transcript_status,
        transcript_kind=transcript_kind,
        session_summary_status=session_summary_status,
        session_summary_missing=session_summary_missing,
        has_audio=has_audio,
        recording_session_id=recording_session_id,
    )
    q = q.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    q = q.offset(offset).limit(limit)
    rows = q.all()
    ids = [c.id for c, _, _ in rows]
    counts = _transcript_counts_for_conversations(db, ids)
    chunk_map = fetch_busy_asr_chunk_progress(db, ids)
    out: list[AdminConversationRow] = []
    for c, at, rss in rows:
        done, tot = chunk_map.get(c.id, (None, None))
        out.append(
            AdminConversationRow(
                c,
                at,
                rss,
                counts.get(c.id, 0),
                asr_chunk_completed=done,
                asr_chunk_total=tot,
            )
        )
    return out


def get_conversation_for_admin(db: Session, conversation_id: UUID) -> Conversation | None:
    return (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.deleted_at.is_(None))
        .first()
    )


def get_owner_user(db: Session, user_id: UUID) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def list_transcripts_for_conversation(
    db: Session, conversation_id: UUID
) -> list[Transcript]:
    return (
        db.query(Transcript)
        .filter(Transcript.conversation_id == conversation_id)
        .order_by(Transcript.revision.asc(), Transcript.id.asc())
        .all()
    )


def get_recording_session_summary_row(
    db: Session, recording_session_id: UUID
) -> RecordingSessionSummary | None:
    return (
        db.query(RecordingSessionSummary)
        .filter(RecordingSessionSummary.recording_session_id == recording_session_id)
        .first()
    )


def list_embeddings_for_conversation(
    db: Session, conversation_id: UUID
) -> list[Embedding]:
    return (
        db.query(Embedding)
        .filter(Embedding.conversation_id == conversation_id)
        .order_by(Embedding.id.asc())
        .all()
    )


def pick_transcript_for_embedding_reindex(
    db: Session,
    conversation: Conversation,
    transcript_id: int | None,
) -> Transcript | None:
    if transcript_id is not None:
        row = (
            db.query(Transcript)
            .filter(
                Transcript.id == transcript_id,
                Transcript.conversation_id == conversation.id,
            )
            .first()
        )
        return row
    if conversation.active_transcript_id is None:
        return None
    row = (
        db.query(Transcript)
        .filter(Transcript.id == conversation.active_transcript_id)
        .first()
    )
    if row is None:
        return None
    if row.status != "success":
        return None
    if row.kind not in ("asr", "asr_diarized"):
        return None
    return row


def has_running_asr_job(db: Session, conversation_id: UUID) -> bool:
    row = (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation_id,
            Transcript.kind == "asr",
            Transcript.status.in_(("pending", "running")),
        )
        .first()
    )
    return row is not None


def has_running_diarization_job(db: Session, conversation_id: UUID) -> bool:
    row = (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation_id,
            Transcript.kind == "asr_diarized",
            Transcript.status == "running",
        )
        .first()
    )
    return row is not None
