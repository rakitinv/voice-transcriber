"""
File upload endpoint for batch transcription.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from core.config import app_config
from core.db import get_db
from core.logging import logger
from core.s3 import storage
from workers.tasks.asr import transcribe_file
from ..models import Conversation, User
from .dependencies import get_current_user

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_audio(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    conversation_id: UUID | None = None,
):
    """
    Upload an audio file for transcription.

    Creates a new conversation if conversation_id is not provided.
    """
    # Validate file size
    file_content = await file.read()
    if len(file_content) > app_config.limits.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum of {app_config.limits.max_file_size_bytes} bytes",
        )

    # Create conversation if needed
    if conversation_id is None:
        from datetime import datetime, timedelta

        from uuid import uuid4

        conversation_id = uuid4()
        s3_prefix = f"users/{current_user.id}/conversations/{conversation_id}"
        expires_at = datetime.utcnow() + timedelta(days=app_config.limits.max_ttl_days)

        conversation = Conversation(
            id=conversation_id,
            user_id=current_user.id,
            title=file.filename or "Uploaded audio",
            s3_prefix=s3_prefix,
            expires_at=expires_at,
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

    # Upload to S3
    storage.upload_audio(
        file_content,
        str(current_user.id),
        str(conversation_id),
        encrypt=True,
    )

    # Queue ASR task
    transcribe_file.delay(
        str(current_user.id),
        str(conversation_id),
        language=None,  # Auto-detect
    )

    logger.info(
        f"Uploaded audio file for conversation {conversation_id}, "
        f"queued transcription task"
    )

    return {
        "conversation_id": str(conversation_id),
        "status": "accepted",
        "message": "File uploaded and transcription queued",
    }
