"""
File upload endpoint for batch transcription.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from core.audio_format import (
    MIN_AUDIO_CONTENT_BYTES,
    AudioFormatError,
    resolve_audio_extension,
)
from core.config import app_config
from core.db import get_db
from core.logging import logger
from core.metrics import UPLOAD_ACCEPTED_TOTAL
from core.s3 import storage
from core.user_language import default_asr_language_hint_from_preferences
from workers.celery_app import celery_app
from ..models import Conversation, User
from .dependencies import get_current_user

router = APIRouter(prefix="/upload", tags=["upload"])


def _default_language_hint(user: User) -> str | None:
    """Return a language hint for ASR (ISO 639-1), or None for auto-detect."""
    return default_asr_language_hint_from_preferences(user.preferences)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_audio(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    conversation_id: UUID | None = None,
    audio_format: str | None = Query(
        default=None,
        description="Явный формат файла: webm, wav, mp3, m4a, aac, ogg, flac, opus",
    ),
):
    """
    Upload an audio file for transcription.

    Creates a new conversation if conversation_id is not provided.

    Формат объекта в S3 (`audio.<ext>`) и для воркера: приоритет query `audio_format`,
    иначе расширение имени файла, иначе Content-Type, иначе webm.
    """
    # Validate file size
    file_content = await file.read()
    if len(file_content) < MIN_AUDIO_CONTENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Audio file is too small ({len(file_content)} bytes). "
                f"Minimum is {MIN_AUDIO_CONTENT_BYTES} bytes; the upload may be truncated or empty."
            ),
        )
    if len(file_content) > app_config.limits.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum of {app_config.limits.max_file_size_bytes} bytes",
        )

    try:
        audio_ext = resolve_audio_extension(
            explicit=audio_format,
            filename=file.filename,
            content_type=file.content_type,
        )
    except AudioFormatError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    # Create conversation if needed
    if conversation_id is None:
        from datetime import timedelta
        from uuid import uuid4

        conversation_id = uuid4()
        s3_prefix = f"users/{current_user.id}/conversations/{conversation_id}"
        expires_at = datetime.utcnow() + timedelta(days=app_config.limits.max_ttl_days)

        now = datetime.now(timezone.utc)
        conversation = Conversation(
            id=conversation_id,
            user_id=current_user.id,
            title=file.filename or "Uploaded audio",
            s3_prefix=s3_prefix,
            expires_at=expires_at,
            recording_session_id=conversation_id,
            previous_conversation_id=None,
            audio_object_ext=audio_ext,
            audio_uploaded_at=now,
        )
        db.add(conversation)
        db.commit()
    else:
        # Verify conversation belongs to user
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
        conversation.audio_object_ext = audio_ext
        conversation.audio_uploaded_at = datetime.now(timezone.utc)
        db.add(conversation)
        db.commit()

    # Upload to S3
    storage.upload_audio(
        file_content,
        str(current_user.id),
        str(conversation_id),
        audio_object_ext=audio_ext,
        encrypt=True,
    )

    # Queue ASR task
    lang_hint = _default_language_hint(current_user)
    # Route long-running batch ASR to the "final" queue by default (ТЗ §17).
    celery_app.send_task(
        "workers.tasks.asr.transcribe_file",
        args=[str(current_user.id), str(conversation_id)],
        kwargs={
            "language": lang_hint,
            "audio_object_ext": audio_ext,
            "transcript_meta_extra": {"processing_tier": "final", "source": "upload"},
        },
        queue="asr_final",
    )

    logger.info(
        f"Uploaded audio file for conversation {conversation_id}, "
        f"queued transcription task"
    )
    UPLOAD_ACCEPTED_TOTAL.inc()

    return {
        "conversation_id": str(conversation_id),
        "audio_object_ext": audio_ext,
        "status": "accepted",
        "message": "File uploaded and transcription queued",
    }
