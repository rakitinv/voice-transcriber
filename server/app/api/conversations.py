"""
Conversation management endpoints.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.config import app_config
from core.db import get_db
from core.logging import logger
from core.s3 import storage
from ..models import Conversation, User
from .dependencies import get_current_user

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    """Request model for creating a conversation."""

    title: str | None = None
    ttl_days: int | None = None


class ConversationResponse(BaseModel):
    """Response model for conversation."""

    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None

    class Config:
        from_attributes = True


class ConversationListResponse(BaseModel):
    """Response model for conversation list."""

    conversations: list[ConversationResponse]
    total: int


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a new conversation."""
    conversation_id = uuid4()
    s3_prefix = f"users/{current_user.id}/conversations/{conversation_id}"

    # Calculate expiration
    ttl_days = data.ttl_days or app_config.limits.max_ttl_days
    if ttl_days > app_config.limits.max_ttl_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"TTL cannot exceed {app_config.limits.max_ttl_days} days",
        )
    expires_at = datetime.utcnow() + timedelta(days=ttl_days)

    conversation = Conversation(
        id=conversation_id,
        user_id=current_user.id,
        title=data.title,
        s3_prefix=s3_prefix,
        expires_at=expires_at,
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
):
    """List user's conversations."""
    conversations = (
        db.query(Conversation)
        .filter(
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .order_by(Conversation.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    total = (
        db.query(Conversation)
        .filter(
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .count()
    )

    return ConversationListResponse(
        conversations=[ConversationResponse.model_validate(c) for c in conversations],
        total=total,
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get a specific conversation."""
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

    return conversation


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

    # Delete from S3
    storage.delete_conversation(str(current_user.id), str(conversation_id))

    # Soft delete in DB
    conversation.deleted_at = datetime.utcnow()
    db.commit()

    logger.info(f"Deleted conversation {conversation_id} for user {current_user.id}")
    return None
