"""
Speaker label endpoints (C1.4): manual rename, LLM identify, apply suggestions.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.models import Conversation, User
from app.services.speaker_display import (
    active_diarized_transcript,
    conversation_for_user,
    merge_speaker_label_maps,
    persist_labels_on_transcript,
)
from core.config import app_config
from core.db import get_db
from core.speaker_labels import (
    applied_llm_entry,
    collect_speaker_ids,
    manual_label_entry,
    PENDING_LLM_SOURCE,
)
from workers.tasks.llm import schedule_speaker_identification

from .dependencies import get_current_user

router = APIRouter(prefix="/conversations", tags=["speakers"])


class SpeakerLabelEntryOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    display_name: str | None = None
    suggested_name: str | None = None
    source: str | None = None
    confidence: float | None = None
    role: str | None = None
    evidence: str | None = None
    updated_at: str | None = None
    updated_by: str | None = None
    applied: bool | None = None


class SpeakersResponse(BaseModel):
    speaker_labels: dict[str, SpeakerLabelEntryOut] = Field(default_factory=dict)
    speaker_ids: list[str] = Field(default_factory=list)
    speaker_identification_status: str | None = None
    speaker_identification_enabled: bool = False


class SpeakerPatchItem(BaseModel):
    speaker_id: str
    display_name: str = Field(min_length=1, max_length=128)


class SpeakersPatchRequest(BaseModel):
    speakers: list[SpeakerPatchItem]


class ApplySuggestionsRequest(BaseModel):
    speaker_ids: list[str] | None = Field(
        default=None,
        description="Subset to accept; null = all pending llm_suggested",
    )


class SpeakersQueuedResponse(BaseModel):
    status: Literal["queued"] = "queued"
    conversation_id: UUID


def _si_cfg():
    return app_config.llm.speaker_identification


def _labels_out(raw: dict[str, Any] | None) -> dict[str, SpeakerLabelEntryOut]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, SpeakerLabelEntryOut] = {}
    for sid, entry in raw.items():
        if isinstance(entry, dict):
            out[str(sid)] = SpeakerLabelEntryOut.model_validate(entry)
    return out


def _require_diarized_conversation(
    db: Session, conversation_id: UUID, user: User
) -> tuple[Conversation, Any]:
    conv = conversation_for_user(db, conversation_id, user.id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    row = active_diarized_transcript(db, conv)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No diarized transcript available",
        )
    segments = (row.transcript_json or {}).get("segments") or []
    return conv, segments


@router.get("/{conversation_id}/speakers", response_model=SpeakersResponse)
async def get_speakers(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    conv, segments = _require_diarized_conversation(db, conversation_id, current_user)
    return SpeakersResponse(
        speaker_labels=_labels_out(conv.speaker_labels),
        speaker_ids=collect_speaker_ids(
            [s for s in segments if isinstance(s, dict)]
        ),
        speaker_identification_status=conv.speaker_identification_status,
        speaker_identification_enabled=_si_cfg().enabled and _si_cfg().mode != "off",
    )


@router.patch("/{conversation_id}/speakers", response_model=SpeakersResponse)
async def patch_speakers(
    conversation_id: UUID,
    body: SpeakersPatchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if not body.speakers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty speakers list")

    conv, segments = _require_diarized_conversation(db, conversation_id, current_user)
    known = set(
        collect_speaker_ids([s for s in segments if isinstance(s, dict)])
    )
    updates: dict[str, dict[str, Any]] = {}
    for item in body.speakers:
        sid = item.speaker_id.strip()
        if sid not in known:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown speaker_id: {sid}",
            )
        updates[sid] = manual_label_entry(item.display_name)

    conv.speaker_labels = merge_speaker_label_maps(conv.speaker_labels, updates)
    row = active_diarized_transcript(db, conv)
    if row is not None:
        persist_labels_on_transcript(db, conv, row, reindex_embedding=True)
    db.commit()
    db.refresh(conv)

    segs = (row.transcript_json or {}).get("segments") if row else segments
    return SpeakersResponse(
        speaker_labels=_labels_out(conv.speaker_labels),
        speaker_ids=collect_speaker_ids(
            [s for s in (segs or []) if isinstance(s, dict)]
        ),
        speaker_identification_status=conv.speaker_identification_status,
        speaker_identification_enabled=_si_cfg().enabled and _si_cfg().mode != "off",
    )


@router.post(
    "/{conversation_id}/speakers/identify",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SpeakersQueuedResponse,
)
async def identify_speakers_endpoint(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    cfg = _si_cfg()
    if not cfg.enabled or cfg.mode == "off":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Speaker identification disabled on server",
        )
    if plugin_registry_get_llm() is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No LLM provider configured",
        )
    conv, _ = _require_diarized_conversation(db, conversation_id, current_user)
    if conv.speaker_identification_status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Speaker identification already running",
        )
    conv.speaker_identification_status = "pending"
    db.commit()
    schedule_speaker_identification(str(current_user.id), str(conversation_id))
    return SpeakersQueuedResponse(conversation_id=conversation_id)


def plugin_registry_get_llm():
    from plugins.loader import plugin_registry

    return plugin_registry.get_llm_provider()


@router.post("/{conversation_id}/speakers/apply-suggestions", response_model=SpeakersResponse)
async def apply_speaker_suggestions(
    conversation_id: UUID,
    body: ApplySuggestionsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    conv, segments = _require_diarized_conversation(db, conversation_id, current_user)
    labels = dict(conv.speaker_labels) if isinstance(conv.speaker_labels, dict) else {}
    if not labels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No speaker suggestions to apply",
        )

    target_ids = body.speaker_ids
    if target_ids is not None:
        wanted = {s.strip() for s in target_ids if s and s.strip()}
    else:
        wanted = {
            sid
            for sid, entry in labels.items()
            if isinstance(entry, dict)
            and str(entry.get("source") or "") == PENDING_LLM_SOURCE
        }

    if not wanted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No matching pending suggestions",
        )

    applied_any = False
    for sid in wanted:
        entry = labels.get(sid)
        if not isinstance(entry, dict):
            continue
        if str(entry.get("source") or "") != PENDING_LLM_SOURCE:
            continue
        name = entry.get("suggested_name") or entry.get("display_name")
        if name is None or not str(name).strip():
            continue
        labels[sid] = applied_llm_entry(
            str(name).strip(),
            role=entry.get("role") if isinstance(entry.get("role"), str) else None,
            confidence=(
                float(entry["confidence"])
                if entry.get("confidence") is not None
                else None
            ),
            source="manual",
        )
        labels[sid]["updated_by"] = "user"
        applied_any = True

    if not applied_any:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No applicable suggestions",
        )

    conv.speaker_labels = labels
    conv.speaker_identification_status = "success"
    row = active_diarized_transcript(db, conv)
    if row is not None:
        persist_labels_on_transcript(db, conv, row, reindex_embedding=True)
    db.commit()
    db.refresh(conv)

    segs = (row.transcript_json or {}).get("segments") if row else segments
    return SpeakersResponse(
        speaker_labels=_labels_out(conv.speaker_labels),
        speaker_ids=collect_speaker_ids(
            [s for s in (segs or []) if isinstance(s, dict)]
        ),
        speaker_identification_status=conv.speaker_identification_status,
        speaker_identification_enabled=_si_cfg().enabled and _si_cfg().mode != "off",
    )
