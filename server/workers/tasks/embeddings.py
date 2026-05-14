"""Index transcript text into embeddings table for semantic search (C2)."""

from __future__ import annotations

from app.models import Embedding, Transcript
from app.services.pipeline_event_write import record_pipeline_event

from ..celery_app import celery_app
from core.config import app_config
from core.db import session_scope
from core.embedding_client import embed_text_sync
from core.logging import logger


def _flatten_transcript_text(row: Transcript) -> str:
    md = (row.transcript_md or "").strip()
    if md:
        return md
    data = row.transcript_json or {}
    parts: list[str] = []
    for seg in data.get("segments") or []:
        if isinstance(seg, dict):
            parts.append(str(seg.get("text") or "").strip())
    return "\n\n".join(p for p in parts if p)


@celery_app.task(name="workers.tasks.embeddings.index_transcript_embedding", bind=True)
def index_transcript_embedding(self, transcript_id: int) -> dict:
    cfg = app_config.embeddings
    if not cfg.enabled:
        return {"status": "skipped", "reason": "disabled"}

    with session_scope() as db:
        row = db.query(Transcript).filter(Transcript.id == int(transcript_id)).first()
        if row is None:
            return {"status": "skipped", "reason": "missing_transcript"}
        if row.status != "success":
            return {"status": "skipped", "reason": "not_success"}

        text = _flatten_transcript_text(row)
        if not text:
            return {"status": "skipped", "reason": "empty_text"}
        text = text[: cfg.max_input_chars]

    try:
        vec = embed_text_sync(text, cfg)
    except Exception as e:
        logger.exception("Embedding RPC failed transcript_id=%s: %s", transcript_id, e)
        raise

    with session_scope() as db:
        row = db.query(Transcript).filter(Transcript.id == int(transcript_id)).first()
        if row is None:
            return {"status": "skipped", "reason": "missing_transcript"}

        existing = (
            db.query(Embedding)
            .filter(Embedding.transcript_id == row.id, Embedding.kind == "full")
            .first()
        )
        if existing:
            existing.vector = vec
        else:
            db.add(
                Embedding(
                    transcript_id=row.id,
                    user_id=row.user_id,
                    conversation_id=row.conversation_id,
                    kind="full",
                    vector=vec,
                )
            )
        record_pipeline_event(
            db,
            conversation_id=row.conversation_id,
            event_type="embedding_indexed",
            transcript_id=row.id,
            detail={"transcript_id": row.id},
        )

    logger.info("Indexed embedding transcript_id=%s dim=%s", transcript_id, len(vec))
    return {"status": "success", "dim": len(vec)}


def schedule_transcript_embedding(transcript_id: int) -> None:
    """Enqueue Celery job when semantic search indexing is enabled."""
    if not app_config.embeddings.enabled:
        return
    try:
        celery_app.send_task(
            "workers.tasks.embeddings.index_transcript_embedding",
            args=[int(transcript_id)],
            queue="llm",
        )
    except Exception:
        logger.exception("schedule_transcript_embedding failed tid=%s", transcript_id)
