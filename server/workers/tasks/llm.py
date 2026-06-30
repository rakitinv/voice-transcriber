"""
LLM summary generation tasks (per-conversation S3 + §7.6 recording_session chain).
Speaker identification after diarization (C1.4).
"""

from __future__ import annotations

from uuid import UUID

from app.models import Conversation, RecordingSessionSummary, Transcript, User
from app.services.speaker_display import (
    active_diarized_transcript,
    merge_speaker_label_maps,
    persist_labels_on_transcript,
)
from app.services.summary_pipeline_events import record_summary_pipeline_events

from ..celery_app import celery_app
from core.config import app_config
from core.db import session_scope
from core.logging import logger
from core.user_language import llm_summary_output_language
from core.recording_session_chain import ordered_chain_segments
from core.s3 import storage
from core.speaker_labels import (
    applied_llm_entry,
    collect_speaker_ids,
    llm_suggestion_entry,
    parse_speaker_identify_json,
    participants_summary_block,
)
from plugins.loader import plugin_registry


def schedule_post_diarization_pipeline(
    user_id: str, conversation_id: str, recording_session_id: str
) -> None:
    """After diarization: optional speaker identify, then rolling session summary."""
    cfg = app_config.llm.speaker_identification
    if cfg.enabled and cfg.mode != "off" and plugin_registry.get_llm_provider() is not None:
        celery_app.send_task(
            "workers.tasks.llm.identify_speakers",
            args=[user_id, conversation_id, recording_session_id],
            queue="llm",
        )
        return
    schedule_recording_session_summary(user_id, recording_session_id)


def schedule_speaker_identification(user_id: str, conversation_id: str) -> None:
    with session_scope() as db:
        conv = db.query(Conversation).filter(Conversation.id == UUID(conversation_id)).first()
        rsid = str(conv.recording_session_id) if conv else conversation_id
    celery_app.send_task(
        "workers.tasks.llm.identify_speakers",
        args=[user_id, conversation_id, rsid],
        queue="llm",
    )


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
        participants = participants_summary_block(
            conv.speaker_labels if isinstance(conv.speaker_labels, dict) else None
        )
        body = f"{participants}{md}" if participants else md
        parts.append(f"## Segment {idx} (`{conv.id}`)\n\n{body}")

    bundle = "\n\n".join(parts) if parts else ""
    if len(bundle) > max_chars:
        bundle = bundle[: max_chars - 80] + "\n\n… *[truncated by session_summary_max_input_chars]*\n"
    return bundle, ids_included


def _sample_speaker_excerpts(
    segments: list[dict],
    *,
    max_chars_per_speaker: int,
    max_speakers: int,
) -> dict[str, str]:
    from core.speaker_labels import resolve_speaker_id

    by_speaker: dict[str, list[dict]] = {}
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        sid = resolve_speaker_id(seg)
        by_speaker.setdefault(sid, []).append(seg)

    speaker_ids = list(by_speaker.keys())[:max_speakers]
    out: dict[str, str] = {}
    for sid in speaker_ids:
        segs = by_speaker[sid]
        if len(segs) <= 5:
            picks = segs
        else:
            picks = []
            for idx in (
                0,
                len(segs) // 4,
                len(segs) // 2,
                (3 * len(segs)) // 4,
                len(segs) - 1,
            ):
                if segs[idx] not in picks:
                    picks.append(segs[idx])
        lines: list[str] = []
        total = 0
        for seg in picks:
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            line = f"[{float(seg.get('start', 0)):.1f}s] {text}"
            if total + len(line) > max_chars_per_speaker:
                break
            lines.append(line)
            total += len(line)
        out[sid] = "\n".join(lines)
    return out


@celery_app.task(name="workers.tasks.llm.identify_speakers", bind=True)
def identify_speakers(
    self, user_id: str, conversation_id: str, recording_session_id: str
) -> dict:
    """LLM suggests display names for diarized speaker_ids (C1.4)."""
    cfg = app_config.llm.speaker_identification
    uid = UUID(user_id)
    cid = UUID(conversation_id)

    if not cfg.enabled or cfg.mode == "off":
        schedule_recording_session_summary(user_id, recording_session_id)
        return {"status": "skipped", "reason": "disabled"}

    provider = plugin_registry.get_llm_provider()
    if provider is None:
        with session_scope() as db:
            conv = db.query(Conversation).filter(Conversation.id == cid).first()
            if conv is not None:
                conv.speaker_identification_status = "skipped"
        schedule_recording_session_summary(user_id, recording_session_id)
        return {"status": "skipped", "reason": "no_provider"}

    try:
        with session_scope() as db:
            conv = (
                db.query(Conversation)
                .filter(Conversation.id == cid, Conversation.user_id == uid)
                .first()
            )
            if conv is None:
                return {"status": "failed", "error": "conversation_not_found"}
            conv.speaker_identification_status = "running"
            row = active_diarized_transcript(db, conv)
            if row is None:
                conv.speaker_identification_status = "failed"
                return {"status": "failed", "error": "no_diarized_transcript"}
            segments = [
                s
                for s in (row.transcript_json or {}).get("segments") or []
                if isinstance(s, dict)
            ]
            if len(collect_speaker_ids(segments)) < 2:
                conv.speaker_identification_status = "skipped"
                schedule_recording_session_summary(user_id, recording_session_id)
                return {"status": "skipped", "reason": "single_speaker"}

            user_row = db.query(User).filter(User.id == uid).first()
            lang = llm_summary_output_language(user_row.preferences) if user_row else "ru"
            excerpts = _sample_speaker_excerpts(
                segments,
                max_chars_per_speaker=cfg.max_input_chars_per_speaker,
                max_speakers=cfg.max_speakers,
            )

        result = provider.suggest_speaker_names(excerpts, output_language=lang)
        parsed = parse_speaker_identify_json(result)
        suggestions = parsed.get("speakers") or []
        if not isinstance(suggestions, list):
            suggestions = []

        updates: dict[str, dict] = {}
        threshold = float(cfg.auto_apply_min_confidence)
        auto_mode = cfg.mode == "auto_apply"

        for item in suggestions:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("speaker_id") or "").strip()
            if not sid:
                continue
            suggested = item.get("suggested_name")
            suggested_s = str(suggested).strip() if suggested is not None else None
            if suggested_s == "":
                suggested_s = None
            role = item.get("role")
            role_s = str(role).strip() if isinstance(role, str) and role.strip() else None
            conf_raw = item.get("confidence")
            confidence = float(conf_raw) if conf_raw is not None else None
            evidence = item.get("evidence")
            evidence_s = (
                str(evidence).strip() if isinstance(evidence, str) and evidence.strip() else None
            )

            if auto_mode and suggested_s and confidence is not None and confidence >= threshold:
                updates[sid] = applied_llm_entry(
                    suggested_s,
                    role=role_s,
                    confidence=confidence,
                    source="llm_auto",
                )
            elif suggested_s:
                updates[sid] = llm_suggestion_entry(
                    suggested_name=suggested_s,
                    role=role_s,
                    confidence=confidence,
                    evidence=evidence_s,
                )

        with session_scope() as db:
            conv = (
                db.query(Conversation)
                .filter(Conversation.id == cid, Conversation.user_id == uid)
                .first()
            )
            if conv is None:
                return {"status": "failed", "error": "conversation_not_found"}
            if updates:
                conv.speaker_labels = merge_speaker_label_maps(conv.speaker_labels, updates)
            conv.speaker_identification_status = "success" if updates else "skipped"
            row = active_diarized_transcript(db, conv)
            if row is not None and any(
                isinstance(v, dict) and v.get("source") == "llm_auto" for v in updates.values()
            ):
                persist_labels_on_transcript(db, conv, row, reindex_embedding=True)

        schedule_recording_session_summary(user_id, recording_session_id)
        return {"status": "success", "suggestions": len(updates)}

    except Exception as e:
        err = str(e)[:2000]
        logger.error("identify_speakers failed conversation=%s: %s", conversation_id, err)
        with session_scope() as db:
            conv = db.query(Conversation).filter(Conversation.id == cid).first()
            if conv is not None:
                conv.speaker_identification_status = "failed"
        schedule_recording_session_summary(user_id, recording_session_id)
        raise


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
