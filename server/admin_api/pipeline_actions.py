"""
Privileged pipeline mutations from Admin API (ADMIN_OPS_CONSOLE §5, §10).

Mutations run here with shared Celery wiring — same JWT as product API; authorization
is ``admin_memberships`` (checked by route dependencies), not a separate admin token.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from admin_api import celery_bridge
from admin_api.audit import record_admin_audit_event
from admin_api.conversations_read import (
    get_conversation_for_admin,
    get_owner_user,
    get_recording_session_summary_row,
    has_running_asr_job,
    has_running_diarization_job,
    pick_transcript_for_embedding_reindex,
)
from admin_api.dependencies import AdminPrincipal
from core.config import app_config
from core.user_language import default_asr_language_hint_from_preferences


def _admin_resummary_llm_provider():
    from plugins.loader import plugin_registry

    return plugin_registry.get_llm_provider()


def admin_enqueue_retranscribe(
    db: Session, principal: AdminPrincipal, conversation_id: UUID
) -> dict[str, str]:
    conv = get_conversation_for_admin(db, conversation_id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conv.audio_uploaded_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No audio uploaded for this conversation",
        )
    if has_running_asr_job(db, conversation_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transcription already running",
        )
    owner = get_owner_user(db, conv.user_id)
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Owner user missing",
        )
    lang_hint = default_asr_language_hint_from_preferences(owner.preferences)
    ext = (conv.audio_object_ext or "webm").lower().lstrip(".")
    celery_bridge.send_pipeline_task(
        "workers.tasks.asr.transcribe_file",
        args=[str(conv.user_id), str(conversation_id)],
        kwargs={
            "language": lang_hint,
            "audio_object_ext": ext,
            "transcript_meta_extra": {"processing_tier": "final", "source": "admin_retranscribe"},
        },
        queue="asr_final",
    )
    record_admin_audit_event(
        admin_user_id=principal.user.id,
        action="retranscribe",
        conversation_id=conversation_id,
    )
    return {"status": "accepted", "conversation_id": str(conversation_id)}


def admin_enqueue_embedding_reindex(
    db: Session,
    principal: AdminPrincipal,
    conversation_id: UUID,
    transcript_id: int | None,
) -> dict[str, str]:
    if not app_config.embeddings.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Embeddings disabled in server configuration",
        )
    conv = get_conversation_for_admin(db, conversation_id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    row = pick_transcript_for_embedding_reindex(db, conv, transcript_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No suitable transcript for embedding reindex",
        )
    from workers.tasks.embeddings import schedule_transcript_embedding

    schedule_transcript_embedding(int(row.id))
    record_admin_audit_event(
        admin_user_id=principal.user.id,
        action="reindex_embedding",
        conversation_id=conversation_id,
        detail=f"transcript_id={row.id}",
    )
    return {
        "status": "accepted",
        "conversation_id": str(conversation_id),
        "transcript_id": str(row.id),
    }


def admin_enqueue_rediarize(
    db: Session, principal: AdminPrincipal, conversation_id: UUID
) -> dict[str, str]:
    if not app_config.diarization.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Диаризация отключена в конфигурации сервера "
                "(diarization.enabled=false в diarization.yaml)."
            ),
        )
    conv = get_conversation_for_admin(db, conversation_id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if has_running_diarization_job(db, conversation_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Diarization already running",
        )
    celery_bridge.send_pipeline_task(
        "workers.tasks.diarization.run_diarization",
        args=[str(conv.user_id), str(conversation_id)],
        queue="diarization",
    )
    record_admin_audit_event(
        admin_user_id=principal.user.id,
        action="rediarize",
        conversation_id=conversation_id,
    )
    return {"status": "accepted", "conversation_id": str(conversation_id)}


def admin_enqueue_resummary(
    db: Session, principal: AdminPrincipal, conversation_id: UUID
) -> dict[str, str]:
    if not app_config.llm.session_summary_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session summary disabled in server configuration",
        )
    if _admin_resummary_llm_provider() is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No LLM provider configured",
        )
    conv = get_conversation_for_admin(db, conversation_id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    rss = get_recording_session_summary_row(db, conv.recording_session_id)
    if rss is not None and rss.status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recording session summary already running",
        )
    celery_bridge.send_pipeline_task(
        "workers.tasks.llm.summarize_recording_session",
        args=[str(conv.user_id), str(conv.recording_session_id)],
        queue="llm",
    )
    record_admin_audit_event(
        admin_user_id=principal.user.id,
        action="resummary",
        conversation_id=conversation_id,
        detail=f"recording_session_id={conv.recording_session_id}",
    )
    return {"status": "accepted", "conversation_id": str(conversation_id)}
