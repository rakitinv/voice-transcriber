"""
Search endpoints for transcripts.

Supports:
- Fulltext search (PostgreSQL tsvector)
- Semantic search (embeddings)
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from core.db import get_db
from core.logging import logger
from ..models import Conversation, Transcript, User
from .dependencies import get_current_user

router = APIRouter(prefix="/search", tags=["search"])


class SearchResult(BaseModel):
    """Search result item."""

    conversation_id: str
    conversation_title: str | None
    transcript_id: int
    text: str
    start: float
    end: float
    speaker: str | None = None


class SearchResponse(BaseModel):
    """Search response."""

    results: list[SearchResult]
    total: int
    mode: str


@router.get("", response_model=SearchResponse)
async def search_transcripts(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(..., description="Search query"),
    mode: Literal["fulltext", "semantic"] = Query("fulltext", description="Search mode"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Search through user's transcripts.

    Supports two modes:
    - fulltext: PostgreSQL fulltext search
    - semantic: Vector similarity search using embeddings
    """
    if mode == "fulltext":
        return await _fulltext_search(q, current_user, db, skip, limit)
    elif mode == "semantic":
        return await _semantic_search(q, current_user, db, skip, limit)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid search mode: {mode}",
        )


async def _fulltext_search(
    query: str, user: User, db: Session, skip: int, limit: int
) -> SearchResponse:
    """Perform fulltext search using PostgreSQL tsvector."""
    # Search in transcript JSON and markdown
    search_term = f"%{query}%"

    # Query transcripts with matching text
    transcripts = (
        db.query(Transcript)
        .join(Conversation)
        .filter(
            Conversation.user_id == user.id,
            Conversation.deleted_at.is_(None),
            or_(
                Transcript.transcript_md.ilike(search_term),
                func.cast(Transcript.transcript_json, db.String).ilike(search_term),
            ),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )

    # Build results from transcript segments
    results = []
    for transcript in transcripts:
        if transcript.transcript_json and "segments" in transcript.transcript_json:
            for seg in transcript.transcript_json["segments"]:
                if query.lower() in seg.get("text", "").lower():
                    results.append(
                        SearchResult(
                            conversation_id=str(transcript.conversation_id),
                            conversation_title=None,  # Would join if needed
                            transcript_id=transcript.id,
                            text=seg.get("text", ""),
                            start=seg.get("start", 0.0),
                            end=seg.get("end", 0.0),
                            speaker=seg.get("speaker"),
                        )
                    )

    # Get total count (simplified)
    total = len(results)

    logger.info(f"Fulltext search for user {user.id}: {len(results)} results")
    return SearchResponse(results=results, total=total, mode="fulltext")


async def _semantic_search(
    query: str, user: User, db: Session, skip: int, limit: int
) -> SearchResponse:
    """
    Perform semantic search using embeddings.

    TODO: Implement vector similarity search.
    For now, returns empty results.
    """
    logger.warning("Semantic search not yet implemented")
    return SearchResponse(results=[], total=0, mode="semantic")
