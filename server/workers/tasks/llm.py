"""
LLM summary generation tasks (per-conversation S3 + §7.6 recording_session chain).
"""

from __future__ import annotations

from uuid import UUID

from app.models import Conversation, RecordingSessionSummary, Transcript, User
from app.services.summary_pipeline_events import record_summary_pipeline_events

from ..celery_app import celery_app
from core.config import app_config
from core.db import session_scope
from core.logging import logger
from core.user_language import llm_summary_output_language
from core.recording_session_chain import ordered_chain_segments
from core.s3 import storage
from plugins.loader import plugin_registry


def schedule_recording_session_summary(user_id: str, recording_session_id: str) -> None:
    """Queue rolling summary for §7 chain after a segment reaches active final transcript."""
    if not app_config.llm.session_summary_enabled:
        return
    if plugin_registry.get_llm_provider() is None:
        logger.warning(
            "recording_session summary skipped: no LLM provider loaded "
            "(enable a provider in configs/llm.yaml)"
        )
        return
    celery_app.send_task(
        "workers.tasks.llm.summarize_recording_session",
        args=[user_id, recording_session_id],
        queue="llm",
    )


@celery_app.task(name="workers.tasks.llm.generate_summary", bind=True)
def generate_summary(
    self, user_id: str, conversation_id: str
) -> dict:
    """
    Generate a summary for a conversation using the configured LLM provider.

    Legacy path: writes summary.md next to conversation artifacts in S3.
    """
    logger.info(f"Starting summary generation for conversation {conversation_id}")

    try:
        transcript = storage.download_transcript_json(user_id, conversation_id, decrypt=True)

        provider = plugin_registry.get_llm_provider()
        if not provider:
            raise ValueError("No LLM provider available")

        lang_code = "en"
        with session_scope() as db:
            u = db.query(User).filter(User.id == UUID(user_id)).first()
            if u is not None:
                lang_code = llm_summary_output_language(u.preferences)

        summary_text = provider.summarize(transcript, output_language=lang_code)

        storage.upload_summary(summary_text, user_id, conversation_id, encrypt=True)

        logger.info(f"Completed summary generation for conversation {conversation_id}")
        return {"status": "success", "summary_length": len(summary_text)}

    except Exception as e:
        logger.error(f"Summary generation failed for {conversation_id}: {e}")
        raise


def _bundle_chain_markdown(
    conversations_ordered: list[Conversation],
    *,
    db,
    max_chars: int,
) -> tuple[str, list[str]]:
    parts: list[str] = []
    ids_included: list[str] = []
    for idx, conv in enumerate(conversations_ordered, start=1):
        row = None
        if conv.active_transcript_id is not None:
            row = (
                db.query(Transcript)
                .filter(
                    Transcript.id == conv.active_transcript_id,
                    Transcript.status == "success",
                )
                .first()
            )
        md = (row.transcript_md or "").strip() if row else ""
        if not md:
            continue
        ids_included.append(str(conv.id))
        parts.append(f"## Segment {idx} (`{conv.id}`)\n\n{md}")

    bundle = "\n\n".join(parts) if parts else ""
    if len(bundle) > max_chars:
        bundle = bundle[: max_chars - 80] + "\n\n… *[truncated by session_summary_max_input_chars]*\n"
    return bundle, ids_included


@celery_app.task(name="workers.tasks.llm.summarize_recording_session", bind=True)
def summarize_recording_session(self, user_id: str, recording_session_id: str) -> dict:
    """
    Rolling Markdown summary for all finalized segments sharing recording_session_id.
    """
    uid = UUID(user_id)
    rsid = UUID(recording_session_id)
    max_chars = max(4096, int(app_config.llm.session_summary_max_input_chars))

    provider = plugin_registry.get_llm_provider()
    if provider is None:
        logger.error("summarize_recording_session: no LLM provider")
        return {"status": "skipped", "reason": "no_provider"}

    ids_included: list[str] = []
    chain_ids: list[UUID] = []
    try:
        with session_scope() as db:
            row = (
                db.query(RecordingSessionSummary)
                .filter(RecordingSessionSummary.recording_session_id == rsid)
                .first()
            )
            if row is None:
                row = RecordingSessionSummary(
                    recording_session_id=rsid,
                    user_id=uid,
                    status="running",
                )
                db.add(row)
            else:
                row.status = "running"
                row.error = None

            convs = (
                db.query(Conversation)
                .filter(
                    Conversation.recording_session_id == rsid,
                    Conversation.user_id == uid,
                    Conversation.deleted_at.is_(None),
                )
                .all()
            )
            ordered = ordered_chain_segments(convs)
            chain_ids = [c.id for c in ordered]
            bundle, ids_included = _bundle_chain_markdown(ordered, db=db, max_chars=max_chars)

            user_row = db.query(User).filter(User.id == uid).first()
            summary_lang = (
                llm_summary_output_language(user_row.preferences) if user_row else "ru"
            )

            if ids_included:
                record_summary_pipeline_events(
                    db,
                    [UUID(x) for x in ids_included],
                    "summary_started",
                )

        if not bundle.strip():
            msg = "no_final_segments"
            with session_scope() as db:
                r2 = (
                    db.query(RecordingSessionSummary)
                    .filter(RecordingSessionSummary.recording_session_id == rsid)
                    .first()
                )
                if r2 is not None:
                    r2.status = "failed"
                    r2.error = msg
                if chain_ids:
                    record_summary_pipeline_events(
                        db,
                        chain_ids,
                        "summary_failed",
                        exc=msg,
                        reason_code="no_final_segments",
                    )
            return {"status": "failed", "error": msg}

        summary_md = provider.summarize_chain_markdown(
            bundle, output_language=summary_lang
        )

        with session_scope() as db:
            r3 = (
                db.query(RecordingSessionSummary)
                .filter(RecordingSessionSummary.recording_session_id == rsid)
                .first()
            )
            if r3 is not None:
                r3.status = "success"
                r3.summary_md = summary_md
                r3.error = None
                r3.meta = {
                    "segment_conversation_ids": ids_included,
                    "segment_count": len(ids_included),
                    "summary_language": summary_lang,
                }
            if ids_included:
                record_summary_pipeline_events(
                    db,
                    [UUID(x) for x in ids_included],
                    "summary_completed",
                )

        storage.upload_recording_session_summary(
            summary_md, user_id, recording_session_id, encrypt=True
        )
        logger.info(
            "Completed recording_session summary session=%s segments=%s",
            recording_session_id,
            len(ids_included),
        )
        return {"status": "success", "segments_used": len(ids_included)}

    except Exception as e:
        err = str(e)[:2000]
        logger.error("summarize_recording_session failed: %s", err)
        with session_scope() as db:
            r4 = (
                db.query(RecordingSessionSummary)
                .filter(RecordingSessionSummary.recording_session_id == rsid)
                .first()
            )
            if r4 is not None:
                r4.status = "failed"
                r4.error = err
            targets = [UUID(x) for x in ids_included] if ids_included else chain_ids
            if targets:
                record_summary_pipeline_events(
                    db,
                    targets,
                    "summary_failed",
                    exc=e,
                )
        raise
