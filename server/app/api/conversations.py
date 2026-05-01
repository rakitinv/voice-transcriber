"""
Conversation management endpoints.
"""

from __future__ import annotations

import json
import mimetypes
import re
from datetime import datetime, timedelta
from typing import Annotated, Literal, Optional
from uuid import UUID, uuid4

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from core.audio_format import MIN_AUDIO_CONTENT_BYTES
from core.config import app_config
from core.db import get_db
from core.logging import logger
from core.s3 import storage
from plugins.loader import plugin_registry
from workers.celery_app import celery_app
from workers.tasks.asr import transcribe_file
from workers.tasks.llm import schedule_recording_session_summary

from ..models import Conversation, RecordingSessionSummary, Transcript, User
from .dependencies import get_current_user
from .upload import _default_language_hint

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str | None = None
    ttl_days: int | None = None
    realtime_mode: Literal["chunk", "windowed"] | None = None
    chunk_ms: int | None = None
    previous_conversation_id: UUID | None = Field(
        default=None,
        description="§7 chain: inherits recording_session_id from this conversation",
    )
    recording_session_id: UUID | None = Field(
        default=None,
        description="Optional session id for chain head (defaults to new conversation id)",
    )


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    recording_session_id: UUID
    previous_conversation_id: UUID | None = None
    client_realtime_mode: str | None = None
    client_chunk_ms: int | None = None
    audio_object_ext: str = "webm"
    duration_seconds: float = 0.0
    language: str = "auto"
    audio_uploaded_at: datetime | None = None


class TranscriptSegmentOut(BaseModel):
    speaker: str
    start: float
    end: float
    text: str


class ConversationDetailResponse(ConversationResponse):
    transcript: list[TranscriptSegmentOut] = Field(default_factory=list)
    summary: str | None = None
    # Active transcript (current published version) metadata.
    transcript_kind: str | None = None
    transcript_status: str | None = None
    transcript_revision: int | None = None
    # ASR phase timing (for asr_diarized rows these come from the source ASR transcript).
    transcript_created_at: datetime | None = None
    transcript_finished_at: datetime | None = None
    # Latest successful diarization info (may be older/newer than active transcript).
    diarization_performed_at: datetime | None = None
    diarization_started_at: datetime | None = None
    diarization_finished_at: datetime | None = None
    # Client: poll GET /conversations/{id} while background ASR/diarization may be in flight.
    refetch_recommended: bool = False
    diarization_status: str | None = None
    # Last failed diarization attempt message (when diarization_status is "failed").
    diarization_error: str | None = None
    # Whether speaker diarization is enabled in server config (diarization.yaml).
    diarization_enabled: bool = False
    # §7.6 rolling summary for recording_session_id (null when feature off).
    recording_session_summary_status: str | None = None
    recording_session_summary_updated_at: datetime | None = None


class RecordingSessionSummaryResponse(BaseModel):
    """Сводка по цепочке автопродления (ТЗ §7.6)."""

    recording_session_id: UUID
    status: str = Field(
        description="disabled | pending | running | success | failed",
    )
    summary_md: str | None = None
    error: str | None = None
    updated_at: datetime | None = None


class RecordingSessionSummaryQueuedResponse(BaseModel):
    """Задача пересчёта сводки поставлена в очередь Celery (`llm`)."""

    recording_session_id: UUID
    status: Literal["queued"] = "queued"


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]
    total: int


class TranscriptVersionOut(BaseModel):
    id: int
    revision: int
    kind: str
    status: str
    created_at: datetime
    updated_at: datetime


class TranscriptVersionsResponse(BaseModel):
    transcripts: list[TranscriptVersionOut] = Field(default_factory=list)


def _validate_client_realtime(mode: str | None, chunk_ms: int | None) -> tuple[str | None, int | None]:
    lim = app_config.limits
    if mode is None and chunk_ms is None:
        return None, None
    if mode is not None and mode not in lim.allowed_realtime_modes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"realtime_mode must be one of {list(lim.allowed_realtime_modes)}",
        )
    if chunk_ms is not None:
        if chunk_ms < lim.chunk_ms_min or chunk_ms > lim.chunk_ms_max:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"chunk_ms must be between {lim.chunk_ms_min} and {lim.chunk_ms_max}",
            )
    return mode, chunk_ms


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a new conversation."""
    mode, chunk_ms = _validate_client_realtime(data.realtime_mode, data.chunk_ms)

    conversation_id = uuid4()
    s3_prefix = f"users/{current_user.id}/conversations/{conversation_id}"

    recording_session_id: UUID = conversation_id
    previous_id: UUID | None = None
    if data.previous_conversation_id is not None:
        prev = (
            db.query(Conversation)
            .filter(
                Conversation.id == data.previous_conversation_id,
                Conversation.user_id == current_user.id,
                Conversation.deleted_at.is_(None),
            )
            .first()
        )
        if prev is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="previous_conversation_id not found",
            )
        recording_session_id = prev.recording_session_id
        previous_id = prev.id
    elif data.recording_session_id is not None:
        recording_session_id = data.recording_session_id

    ttl_days = data.ttl_days or app_config.limits.max_ttl_days
    if ttl_days > app_config.limits.max_ttl_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"TTL cannot exceed {app_config.limits.max_ttl_days} days",
        )
    if ttl_days < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TTL must be at least 1 day",
        )
    expires_at = datetime.utcnow() + timedelta(days=ttl_days)

    conversation = Conversation(
        id=conversation_id,
        user_id=current_user.id,
        title=data.title,
        s3_prefix=s3_prefix,
        expires_at=expires_at,
        recording_session_id=recording_session_id,
        previous_conversation_id=previous_id,
        client_realtime_mode=mode,
        client_chunk_ms=chunk_ms,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    logger.info(f"Created conversation {conversation_id} for user {current_user.id}")
    return conversation


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    skip: int = 0,
    limit: int = 50,
    recording_session_id: UUID | None = None,
):
    """List user's conversations; optional filter by §7 recording session."""
    base_filters = (
        Conversation.user_id == current_user.id,
        Conversation.deleted_at.is_(None),
    )
    if recording_session_id is not None:
        base_filters = (
            *base_filters,
            Conversation.recording_session_id == recording_session_id,
        )

    conversations = (
        db.query(Conversation)
        .filter(*base_filters)
        .order_by(Conversation.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    total = db.query(Conversation).filter(*base_filters).count()

    durations, languages = _list_transcript_duration_language(
        db, current_user, conversations
    )
    conv_rows: list[ConversationResponse] = []
    for c in conversations:
        base = ConversationResponse.model_validate(c)
        conv_rows.append(
            base.model_copy(
                update={
                    "duration_seconds": durations.get(c.id, 0.0),
                    "language": languages.get(c.id, "auto"),
                }
            )
        )

    return ConversationListResponse(
        conversations=conv_rows,
        total=total,
    )


def _fast_transcript_row(db: Session, conversation: Conversation) -> Transcript | None:
    rows = (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation.id,
            Transcript.user_id == conversation.user_id,
            Transcript.status == "success",
        )
        .order_by(Transcript.revision.desc())
        .all()
    )
    for r in rows:
        meta = r.meta if isinstance(r.meta, dict) else {}
        if meta.get("processing_tier") == "fast":
            return r
    return None


def _final_view_transcript_row(db: Session, conversation: Conversation) -> Transcript | None:
    """Стадия «final» для UI: сначала успешная диаризация, иначе последний ASR не из ветки fast."""
    diar = (
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
    if diar is not None:
        return diar
    rows = (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation.id,
            Transcript.user_id == conversation.user_id,
            Transcript.kind == "asr",
            Transcript.status == "success",
        )
        .order_by(Transcript.revision.desc())
        .all()
    )
    for r in rows:
        meta = r.meta if isinstance(r.meta, dict) else {}
        if meta.get("processing_tier") == "fast":
            continue
        return r
    return None


def _active_transcript_row(db: Session, conversation: Conversation) -> Transcript | None:
    """
    Return the active transcript row for a conversation.

    Scheme 2: prefer Conversation.active_transcript_id; fallback to latest successful revision.
    """
    if conversation.active_transcript_id is not None:
        row = (
            db.query(Transcript)
            .filter(
                Transcript.id == conversation.active_transcript_id,
                Transcript.conversation_id == conversation.id,
                Transcript.user_id == conversation.user_id,
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
            Transcript.status == "success",
        )
        .order_by(Transcript.revision.desc())
        .first()
    )


def _refetch_recommended(db: Session, conversation: Conversation, row: Transcript | None) -> bool:
    """
    True while ASR or diarization may still change the active transcript / metadata.

    Used by WebUI polling; avoids infinite polling when diarization is disabled or has failed.
    """
    if row is None:
        return True
    if row.status in ("pending", "running"):
        return True

    # Final ASR (§17) may run while active_transcript_id still points at fast — keep polling.
    busy_other = (
        db.query(Transcript.id)
        .filter(
            Transcript.conversation_id == conversation.id,
            Transcript.user_id == conversation.user_id,
            Transcript.status.in_(("pending", "running")),
        )
        .limit(1)
        .first()
    )
    if busy_other is not None:
        return True

    latest_diar = (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation.id,
            Transcript.user_id == conversation.user_id,
            Transcript.kind == "asr_diarized",
        )
        .order_by(Transcript.revision.desc())
        .first()
    )
    if latest_diar is not None and latest_diar.status in ("pending", "running"):
        return True

    if not app_config.diarization.enabled:
        return False
    if row.status != "success" or row.kind != "asr":
        return False
    if conversation.active_transcript_id != row.id:
        return False

    if latest_diar is None:
        return True
    if latest_diar.status == "failed" and latest_diar.revision > row.revision:
        return False
    if latest_diar.status == "success" and latest_diar.revision > row.revision:
        # Diarized revision exists; keep polling until active pointer moves off plain ASR.
        return conversation.active_transcript_id == row.id
    return False


def _list_transcript_duration_language(
    db: Session, user: User, conversations: list[Conversation]
) -> tuple[dict[UUID, float], dict[UUID, str]]:
    """
    Batch-compute list-row transcript metrics (duration + detected language).

    Mirrors `get_conversation` transcript selection (`_active_transcript_row`) without N+1 queries.
    """
    if not conversations:
        return {}, {}

    user_id = user.id
    conv_ids = [c.id for c in conversations]
    active_ids = [c.active_transcript_id for c in conversations if c.active_transcript_id is not None]

    active_rows: dict[UUID, Transcript] = {}
    if active_ids:
        rows = (
            db.query(Transcript)
            .filter(
                Transcript.id.in_(active_ids),
                Transcript.user_id == user_id,
                Transcript.conversation_id.in_(conv_ids),
            )
            .all()
        )
        for r in rows:
            active_rows[r.conversation_id] = r

    missing_conv_ids = [cid for cid in conv_ids if cid not in active_rows]
    latest_success: dict[UUID, Transcript] = {}
    if missing_conv_ids:
        rows = (
            db.query(Transcript)
            .filter(
                Transcript.user_id == user_id,
                Transcript.conversation_id.in_(missing_conv_ids),
                Transcript.status == "success",
            )
            .order_by(Transcript.conversation_id.asc(), Transcript.revision.desc())
            .all()
        )
        for r in rows:
            # First row per conversation_id wins due to revision.desc() ordering.
            if r.conversation_id not in latest_success:
                latest_success[r.conversation_id] = r

    durations: dict[UUID, float] = {cid: 0.0 for cid in conv_ids}
    languages: dict[UUID, str] = {cid: "auto" for cid in conv_ids}

    for cid in conv_ids:
        row = active_rows.get(cid) or latest_success.get(cid)
        if row is None:
            continue
        tjson = row.transcript_json if row.transcript_json else {"segments": []}
        segments = _segments_from_json(tjson)
        durations[cid] = _duration_from_segments(segments)
        languages[cid] = _display_language_for_viewer(user, tjson, segments)

    return durations, languages


def _segments_from_json(data: dict) -> list[TranscriptSegmentOut]:
    out: list[TranscriptSegmentOut] = []
    for seg in data.get("segments") or []:
        out.append(
            TranscriptSegmentOut(
                speaker=str(seg.get("speaker", "Speaker 1")),
                start=float(seg.get("start", 0.0)),
                end=float(seg.get("end", 0.0)),
                text=str(seg.get("text", "")),
            )
        )
    return out


def _duration_from_segments(segments: list[TranscriptSegmentOut]) -> float:
    if not segments:
        return 0.0
    return max(s.end for s in segments)


def _detected_language_from_transcript_json(
    tjson: dict, segments: list[TranscriptSegmentOut]
) -> str | None:
    """Language from first ASR segment when present and meaningful; else None."""
    if not segments or not (segments[0].text or "").strip():
        return None
    first = (tjson.get("segments") or [{}])[0]
    raw = str(first.get("language", "") or "").strip().lower()
    if not raw or raw in ("auto", "—", "-"):
        return None
    return raw


def _display_language_for_viewer(
    user: User, tjson: dict, segments: list[TranscriptSegmentOut]
) -> str:
    """
    UI-facing language: detected from transcript when available, otherwise the user's
    default_language preference (same hint as batch ASR), else 'auto'.
    """
    det = _detected_language_from_transcript_json(tjson, segments)
    if det:
        return det
    hint = _default_language_hint(user)
    return hint if hint else "auto"


def _diarization_error_from_meta(row: Transcript | None) -> str | None:
    if row is None or row.status != "failed":
        return None
    meta = row.meta if isinstance(row.meta, dict) else {}
    raw = meta.get("diarization_error") or meta.get("error")
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def _resolve_asr_source_row(db: Session, row: Transcript | None) -> Transcript | None:
    """For a diarized transcript row, load the ASR source row; otherwise return `row`."""
    if row is None:
        return None
    if row.kind != "asr_diarized":
        return row
    meta = row.meta if isinstance(row.meta, dict) else {}
    sid = meta.get("source_transcript_id")
    if sid is not None:
        try:
            sid_int = int(sid)
        except (TypeError, ValueError):
            sid_int = None
        if sid_int is not None:
            src = (
                db.query(Transcript)
                .filter(
                    Transcript.id == sid_int,
                    Transcript.conversation_id == row.conversation_id,
                    Transcript.user_id == row.user_id,
                )
                .first()
            )
            if src is not None:
                return src
    rev = meta.get("source_revision")
    if rev is not None:
        try:
            rev_int = int(rev)
        except (TypeError, ValueError):
            rev_int = None
        if rev_int is not None:
            src = (
                db.query(Transcript)
                .filter(
                    Transcript.conversation_id == row.conversation_id,
                    Transcript.user_id == row.user_id,
                    Transcript.revision == rev_int,
                )
                .first()
            )
            if src is not None:
                return src
    return row


def _asr_phase_timestamps(db: Session, row: Transcript | None) -> tuple[datetime | None, datetime | None]:
    """Start/end for the ASR phase matching the transcript row shown to the client."""
    asr_row = _resolve_asr_source_row(db, row)
    if asr_row is None:
        return None, None
    finished = asr_row.updated_at if asr_row.status == "success" else None
    return asr_row.created_at, finished


def _diarization_phase_timestamps(
    latest_diar: Transcript | None,
) -> tuple[datetime | None, datetime | None]:
    """Diarization job start; end when the attempt finished (success or failed)."""
    if latest_diar is None:
        return None, None
    started = latest_diar.created_at
    finished = (
        latest_diar.updated_at if latest_diar.status in ("success", "failed") else None
    )
    return started, finished


def _safe_audio_ext(raw: str | None) -> str:
    e = (raw or "webm").lower().lstrip(".")
    if not re.fullmatch(r"[a-z0-9]{1,16}", e):
        return "webm"
    return e


def _recording_session_summary_sidebar(
    db: Session,
    conversation: Conversation,
) -> tuple[str | None, datetime | None]:
    if not app_config.llm.session_summary_enabled:
        return None, None
    row = (
        db.query(RecordingSessionSummary)
        .filter(
            RecordingSessionSummary.recording_session_id
            == conversation.recording_session_id,
            RecordingSessionSummary.user_id == conversation.user_id,
        )
        .first()
    )
    if row is None:
        return "pending", None
    return row.status, row.updated_at


@router.get("/{conversation_id}/session-summary", response_model=RecordingSessionSummaryResponse)
async def get_recording_session_summary(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Rolling Markdown summary for §7 recording_session_id chain."""
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    rsid = conversation.recording_session_id
    if not app_config.llm.session_summary_enabled:
        return RecordingSessionSummaryResponse(
            recording_session_id=rsid,
            status="disabled",
            summary_md=None,
            error=None,
            updated_at=None,
        )

    row = (
        db.query(RecordingSessionSummary)
        .filter(
            RecordingSessionSummary.recording_session_id == rsid,
            RecordingSessionSummary.user_id == current_user.id,
        )
        .first()
    )
    if row is None:
        return RecordingSessionSummaryResponse(
            recording_session_id=rsid,
            status="pending",
            summary_md=None,
            error=None,
            updated_at=None,
        )
    return RecordingSessionSummaryResponse(
        recording_session_id=rsid,
        status=row.status,
        summary_md=row.summary_md,
        error=row.error,
        updated_at=row.updated_at,
    )


@router.post(
    "/{conversation_id}/session-summary/retry",
    response_model=RecordingSessionSummaryQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_recording_session_summary(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Повторно поставить в очередь rolling-summary по `recording_session_id` (после починки LLM/Ollama)."""
    if not app_config.llm.session_summary_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session summary disabled on server",
        )
    if plugin_registry.get_llm_provider() is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No LLM provider configured",
        )
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    rsid = conversation.recording_session_id
    schedule_recording_session_summary(str(current_user.id), str(rsid))
    logger.info(
        "Queued recording_session summary retry user=%s recording_session_id=%s",
        current_user.id,
        rsid,
    )
    return RecordingSessionSummaryQueuedResponse(recording_session_id=rsid)


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    tier: Literal["auto", "fast", "final"] = Query(
        "auto",
        description="Вариант транскрипта: auto=активный указатель; fast/final=ветки §17",
    ),
):
    """Get a specific conversation with transcript (from S3 when available)."""
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )

    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    active_row = _active_transcript_row(db, conversation)
    if tier == "auto":
        row = active_row
    elif tier == "fast":
        row = _fast_transcript_row(db, conversation)
    elif tier == "final":
        row = _final_view_transcript_row(db, conversation)
    else:
        row = active_row

    tjson = (row.transcript_json if row and row.transcript_json else {"segments": []})
    summary = row.summary_md if row else None
    segments = _segments_from_json(tjson)
    lang = _display_language_for_viewer(current_user, tjson, segments)

    base = ConversationResponse.model_validate(conversation)

    diarized_row = (
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
    latest_diar = (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation.id,
            Transcript.user_id == conversation.user_id,
            Transcript.kind == "asr_diarized",
        )
        .order_by(Transcript.revision.desc())
        .first()
    )
    asr_started, asr_finished = _asr_phase_timestamps(db, row)
    diar_started, diar_finished = _diarization_phase_timestamps(latest_diar)
    sess_sum_status, sess_sum_at = _recording_session_summary_sidebar(db, conversation)

    # `ConversationResponse` already defines duration_seconds/language; model_dump()
    # includes them — do not pass duplicates to ConversationDetailResponse(...).
    return ConversationDetailResponse(
        **base.model_dump(exclude={"duration_seconds", "language"}),
        duration_seconds=_duration_from_segments(segments),
        language=lang,
        transcript=segments,
        summary=summary,
        transcript_kind=(row.kind if row else None),
        transcript_status=(row.status if row else None),
        transcript_revision=(row.revision if row else None),
        transcript_created_at=asr_started,
        transcript_finished_at=asr_finished,
        # Successful diarization completion (backward-compatible alias for diarization_finished_at).
        diarization_performed_at=(diarized_row.updated_at if diarized_row else None),
        diarization_started_at=diar_started,
        diarization_finished_at=diar_finished,
        diarization_status=(latest_diar.status if latest_diar else None),
        diarization_error=(
            _diarization_error_from_meta(latest_diar)
            if latest_diar is not None and latest_diar.status == "failed"
            else None
        ),
        diarization_enabled=app_config.diarization.enabled,
        refetch_recommended=_refetch_recommended(db, conversation, active_row),
        recording_session_summary_status=sess_sum_status,
        recording_session_summary_updated_at=sess_sum_at,
    )


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    export_format: Literal["md", "json"] = Query(..., alias="format"),
    tier: Literal["auto", "fast", "final"] = Query(
        "auto",
        description="Какую ветку экспортировать (§17); auto=активный транскрипт",
    ),
):
    """Export transcript as Markdown or JSON (ТЗ Phase A)."""
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    uid = str(current_user.id)
    cid = str(conversation_id)

    active_row = _active_transcript_row(db, conversation)
    if tier == "auto":
        row = active_row
    elif tier == "fast":
        row = _fast_transcript_row(db, conversation)
    elif tier == "final":
        row = _final_view_transcript_row(db, conversation)
    else:
        row = active_row

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found")

    diarized_row = (
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

    latest_any_diar = (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation.id,
            Transcript.user_id == conversation.user_id,
            Transcript.kind == "asr_diarized",
        )
        .order_by(Transcript.revision.desc())
        .first()
    )

    tjson = (row.transcript_json if row and row.transcript_json else {"segments": []})
    segments_out = _segments_from_json(tjson)
    dur = _duration_from_segments(segments_out)
    det_lang = _display_language_for_viewer(current_user, tjson, segments_out)

    audio_up = (
        conversation.audio_uploaded_at.isoformat()
        if conversation.audio_uploaded_at is not None
        else None
    )

    asr_started, asr_finished = _asr_phase_timestamps(db, row)
    trans_parts: list[str] = []
    if asr_started is not None:
        trans_parts.append(f"начата: {asr_started.isoformat()}")
    if asr_finished is not None:
        trans_parts.append(f"завершена: {asr_finished.isoformat()}")
    elif row.status in ("pending", "running"):
        trans_parts.append("распознавание в процессе")
    trans_tail = (" · " + " · ".join(trans_parts)) if trans_parts else ""

    di_s, di_f = _diarization_phase_timestamps(latest_any_diar)
    if latest_any_diar is None:
        diar_tail = "не выполнялась"
    elif latest_any_diar.status == "success":
        if di_s is not None and di_f is not None:
            diar_tail = f"начата: {di_s.isoformat()} · завершена: {di_f.isoformat()}"
        else:
            diar_tail = "не выполнялась"
    elif latest_any_diar.status == "failed":
        err_tail = _diarization_error_from_meta(latest_any_diar)
        if di_s is not None and di_f is not None:
            diar_tail = (
                f"начата: {di_s.isoformat()} · завершена: {di_f.isoformat()}"
                + (f" — {err_tail}" if err_tail else " — ошибка")
            )
        else:
            diar_tail = (
                f"ошибка (попытка завершена: {latest_any_diar.updated_at.isoformat()})"
                + (f" — {err_tail}" if err_tail else "")
            )
    elif latest_any_diar.status in ("pending", "running"):
        diar_tail = (
            f"начата: {di_s.isoformat()} · в процессе"
            if di_s is not None
            else "в процессе"
        )
    else:
        diar_tail = "не выполнялась"

    meta = {
        "conversation_id": cid,
        "conversation_created_at": conversation.created_at.isoformat(),
        "audio_uploaded_at": audio_up,
        "audio_object_ext": _safe_audio_ext(conversation.audio_object_ext),
        "duration_seconds": dur,
        "detected_language": det_lang,
        "transcript_kind": (row.kind if row else None),
        "transcript_revision": (row.revision if row else None),
        "transcript_status": (row.status if row else None),
        "transcription_started_at": (asr_started.isoformat() if asr_started else None),
        "transcription_finished_at": (asr_finished.isoformat() if asr_finished else None),
        "diarization_started_at": (di_s.isoformat() if di_s else None),
        "diarization_finished_at": (di_f.isoformat() if di_f else None),
        "diarization_performed_at": (
            diarized_row.updated_at.isoformat() if diarized_row else None
        ),
        # Backward-compatible aggregate timestamp for older clients / UI rewriters.
        "uploaded_at": audio_up or conversation.created_at.isoformat(),
    }

    if export_format == "json":
        data = row.transcript_json if row.transcript_json else None
        if data is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found")
        # Preserve existing contract (`segments` etc.) and add metadata alongside.
        if isinstance(data, dict):
            data = dict(data)
            existing = data.get("_meta")
            merged = dict(meta)
            if isinstance(existing, dict):
                merged = {**existing, **merged}
            data["_meta"] = merged
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=body,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="transcript-{cid}.json"'
            },
        )

    # markdown
    if row.transcript_md:
        md_body = row.transcript_md
    else:
        data = row.transcript_json or {"segments": []}
        lines = []
        for seg in data.get("segments") or []:
            sp = seg.get("speaker", "Speaker 1")
            lines.append(
                f"**{sp}** ({seg.get('start', 0):.1f}s–{seg.get('end', 0):.1f}s): {seg.get('text', '')}"
            )
        md_body = "\n\n".join(lines) if lines else "_No transcript._\n"

    header = (
        f"# Расшифровка\n\n"
        f"- Разговор: `{cid}`\n"
        f"- Создан разговор: {meta['conversation_created_at']}\n"
        f"- Аудио загружено: {meta['audio_uploaded_at'] or 'нет данных'}\n"
        f"- Параметры аудио: файл `audio.{meta['audio_object_ext']}`, "
        f"длительность по расшифровке ~{float(meta['duration_seconds']):.1f} с, язык: {meta['detected_language']}\n"
        f"- Транскрибация: вид={row.kind!s}, ревизия={row.revision}, статус={row.status!s}"
        f"{trans_tail}\n"
        f"- Диаризация: {diar_tail}\n\n"
        f"---\n\n"
    )
    md = header + md_body

    return Response(
        content=md.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="transcript-{cid}.md"'},
    )


@router.get("/{conversation_id}/audio")
async def download_conversation_audio(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Download the original uploaded audio for this conversation (decrypted from S3)."""
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    uid = str(current_user.id)
    cid = str(conversation_id)
    ext = _safe_audio_ext(conversation.audio_object_ext)
    try:
        body = storage.download_audio(uid, cid, audio_object_ext=ext, decrypt=True)
    except ClientError as e:
        code = (e.response or {}).get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Audio not found",
            ) from e
        raise

    if len(body) < MIN_AUDIO_CONTENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Stored audio is too small ({len(body)} bytes) to be a valid recording. "
                "Re-upload the file. If this persists, check API and worker share the same VT_JWT_SECRET "
                "(otherwise decrypt can yield garbage)."
            ),
        )

    guessed, _ = mimetypes.guess_type(f"x.{ext}")
    media_type = guessed or "application/octet-stream"
    filename = f"recording-{cid}.{ext}"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete a conversation and all its files."""
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )

    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    storage.delete_conversation(str(current_user.id), str(conversation_id))

    conversation.deleted_at = datetime.utcnow()
    db.commit()

    logger.info(f"Deleted conversation {conversation_id} for user {current_user.id}")
    return None


@router.post("/{conversation_id}/retranscribe", status_code=status.HTTP_202_ACCEPTED)
async def retranscribe_conversation(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Queue full-file ASR again for the existing uploaded audio (new transcript revision).

    Does not run diarization by itself; if enabled, diarization is queued after ASR succeeds
    (same as upload flow).
    """
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    if conversation.audio_uploaded_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No audio uploaded for this conversation",
        )

    running = (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation_id,
            Transcript.user_id == current_user.id,
            Transcript.kind == "asr",
            Transcript.status.in_(("pending", "running")),
        )
        .first()
    )
    if running is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transcription already running",
        )

    ext = (conversation.audio_object_ext or "webm").lower().lstrip(".")
    lang_hint = _default_language_hint(current_user)
    celery_app.send_task(
        "workers.tasks.asr.transcribe_file",
        args=[str(current_user.id), str(conversation_id)],
        kwargs={
            "language": lang_hint,
            "audio_object_ext": ext,
            "transcript_meta_extra": {"processing_tier": "final", "source": "retranscribe"},
        },
        queue="asr_final",
    )
    logger.info("Queued re-transcription for conversation %s", conversation_id)
    return {"status": "accepted", "conversation_id": str(conversation_id)}


@router.post("/{conversation_id}/diarize", status_code=status.HTTP_202_ACCEPTED)
async def diarize_conversation(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Queue diarization re-run for this conversation.

    UI must confirm with the user: the operation creates a new transcript version and
    promotes it to active on success.
    """
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Anti-double-click guard: if a diarization job is already running, do not enqueue another.
    running = (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation_id,
            Transcript.user_id == current_user.id,
            Transcript.kind == "asr_diarized",
            Transcript.status == "running",
        )
        .first()
    )
    if running is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Diarization already running",
        )

    if not app_config.diarization.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Диаризация отключена в конфигурации сервера "
                "(diarization.enabled=false в diarization.yaml)."
            ),
        )

    celery_app.send_task(
        "workers.tasks.diarization.run_diarization",
        args=[str(current_user.id), str(conversation_id)],
        queue="diarization",
    )
    return {"status": "accepted", "conversation_id": str(conversation_id)}


@router.get("/{conversation_id}/transcripts", response_model=TranscriptVersionsResponse)
async def list_conversation_transcripts(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List transcript versions for a conversation (backend-only; UI may add later).
    """
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    rows = (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation_id,
            Transcript.user_id == current_user.id,
        )
        .order_by(Transcript.revision.desc())
        .all()
    )
    return TranscriptVersionsResponse(
        transcripts=[
            TranscriptVersionOut(
                id=r.id,
                revision=r.revision,
                kind=r.kind,
                status=r.status,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]
    )
