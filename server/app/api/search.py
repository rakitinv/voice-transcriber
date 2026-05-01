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
import numpy as np
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from core.config import app_config
from core.db import get_db
from core.embedding_client import embed_text_sync
from core.logging import logger
from ..models import Conversation, Embedding, Transcript, User
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

    # Query only the active transcript per conversation (Scheme 2).
    transcripts = (
        db.query(Transcript)
        .join(Conversation)
        .filter(
            Conversation.user_id == user.id,
            Conversation.deleted_at.is_(None),
            Conversation.active_transcript_id == Transcript.id,
            or_(
                Transcript.transcript_md.ilike(search_term),
                cast(Transcript.transcript_json, String).ilike(search_term),
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


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


async def _semantic_search(
    query: str, user: User, db: Session, skip: int, limit: int
) -> SearchResponse:
    """Cosine similarity over stored ``Embedding(kind=full)`` for active transcripts."""
    cfg = app_config.embeddings
    if not cfg.enabled:
        logger.info("Semantic search skipped (embeddings.disabled)")
        return SearchResponse(results=[], total=0, mode="semantic")

    qtext = query.strip()[: cfg.max_input_chars]
    if not qtext:
        return SearchResponse(results=[], total=0, mode="semantic")

    try:
        qvec = embed_text_sync(qtext, cfg)
    except Exception as e:
        logger.exception("Semantic query embedding failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding service unavailable",
        ) from e

    rows = (
        db.query(Embedding, Conversation, Transcript)
        .join(
            Transcript,
            Transcript.id == Embedding.transcript_id,
        )
        .join(Conversation, Conversation.id == Embedding.conversation_id)
        .filter(
            Embedding.user_id == user.id,
            Conversation.user_id == user.id,
            Conversation.deleted_at.is_(None),
            Conversation.active_transcript_id == Transcript.id,
            Embedding.kind == "full",
            Transcript.status == "success",
        )
        .all()
    )

    scored: list[tuple[float, Embedding, Conversation, Transcript]] = []
    for emb, conv, trow in rows:
        sim = _cosine_similarity(qvec, emb.vector)
        scored.append((sim, emb, conv, trow))

    scored.sort(key=lambda x: x[0], reverse=True)
    total = len(scored)
    window = scored[skip : skip + limit]

    results: list[SearchResult] = []
    for sim, _emb, conv, trow in window:
        text_snip = ""
        start_f = 0.0
        end_f = 0.0
        speaker = None
        tjson = trow.transcript_json or {}
        segs = tjson.get("segments") if isinstance(tjson.get("segments"), list) else []
        if segs and isinstance(segs[0], dict):
            text_snip = str(segs[0].get("text") or "")
            start_f = float(segs[0].get("start", 0.0))
            end_f = float(segs[0].get("end", 0.0))
            speaker = segs[0].get("speaker")
        elif trow.transcript_md:
            text_snip = trow.transcript_md.strip()[:800]
        results.append(
            SearchResult(
                conversation_id=str(conv.id),
                conversation_title=conv.title,
                transcript_id=trow.id,
                text=text_snip or f"(semantic score={sim:.4f})",
                start=start_f,
                end=end_f,
                speaker=speaker,
            )
        )

    logger.info("Semantic search user=%s hits=%s total=%s", user.id, len(results), total)
    return SearchResponse(results=results, total=total, mode="semantic")
