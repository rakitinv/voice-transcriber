"""
Finalize realtime сессии: сохранить аудио в S3, запись fast-транскрипта в БД, постановка final ASR в Celery (ТЗ §17).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.models import Conversation, Transcript

from core.audio_format import MIN_AUDIO_CONTENT_BYTES
from core.db import session_scope
from core.logging import logger
from core.pcm_audio import pcm_s16le_mono_to_wav
from core.realtime_merge import merge_realtime_partials
from core.s3 import storage
from workers.celery_app import celery_app

# ~100 ms PCM mono s16 @ 16 kHz — ниже нет смысла слать в полный ASR
MIN_REALTIME_FINALIZE_PCM_BYTES = 3200


def _fast_segments_from_partials(
    partial_texts: list[str] | list[dict],
    pcm_len: int,
    sample_rate: int,
    *,
    step_s: float | None = None,
    overlap_s: float | None = None,
) -> list[dict]:
    if partial_texts and isinstance(partial_texts[0], dict):
        merged = merge_realtime_partials(
            list(partial_texts),  # type: ignore[arg-type]
            step_s=float(step_s or 2.0),
            overlap_s=float(overlap_s or 0.0),
        )
        if merged:
            return merged

    str_texts = [str(t) for t in partial_texts if isinstance(t, str) and str(t).strip()]
    dur = float(pcm_len) / float(sample_rate * 2) if pcm_len > 0 else 0.0
    text = "\n\n".join(t.strip() for t in str_texts)
    if not text:
        text = "[realtime fast — нет текста частичных распознаваний]"
    return [
        {
            "speaker": "Speaker 1",
            "start": 0.0,
            "end": max(dur, 0.1),
            "text": text,
        }
    ]


def _segments_to_md(segments: list[dict]) -> str:
    lines: list[str] = []
    for seg in segments:
        lines.append(
            f"**{seg.get('speaker', 'Speaker 1')}** "
            f"({float(seg.get('start', 0)):.1f}s–{float(seg.get('end', 0)):.1f}s): "
            f"{seg.get('text', '')}"
        )
    return "\n\n".join(lines) if lines else "_No transcript._\n"


def _has_non_fast_final_row(db, conversation_id: UUID, user_id: UUID) -> bool:
    rows = (
        db.query(Transcript)
        .filter(
            Transcript.conversation_id == conversation_id,
            Transcript.user_id == user_id,
            Transcript.kind == "asr",
            Transcript.status.in_(("pending", "running", "success")),
        )
        .all()
    )
    for r in rows:
        meta = r.meta if isinstance(r.meta, dict) else {}
        if meta.get("processing_tier") == "fast":
            continue
        return True
    return False


def persist_fast_snapshot(
    *,
    user_id: str,
    conversation_id: str,
    partial_texts: list[str] | list[dict],
    pcm_len: int,
    snapshot_seq: int,
    step_s: float | None = None,
    overlap_s: float | None = None,
) -> bool:
    """
    Upsert fast transcript from accumulated partials (REALTIME_FAST_FINAL_V2 §7.1).
    Does not queue Celery or upload audio.
    """
    if not partial_texts:
        return False

    uid = UUID(user_id)
    cid = UUID(conversation_id)
    fast_segments = _fast_segments_from_partials(
        partial_texts,
        pcm_len,
        16_000,
        step_s=step_s,
        overlap_s=overlap_s,
    )
    fast_json = {"segments": fast_segments}
    fast_md = _segments_to_md(fast_segments)

    try:
        fast_row_id: int | None = None
        with session_scope() as db:
            conv = (
                db.query(Conversation)
                .filter(Conversation.id == cid, Conversation.user_id == uid)
                .with_for_update()
                .first()
            )
            if conv is None:
                return False

            existing: Transcript | None = None
            rows = (
                db.query(Transcript)
                .filter(
                    Transcript.conversation_id == cid,
                    Transcript.user_id == uid,
                    Transcript.kind == "asr",
                    Transcript.status == "success",
                )
                .order_by(Transcript.revision.desc())
                .all()
            )
            for r in rows:
                meta = r.meta if isinstance(r.meta, dict) else {}
                if (
                    meta.get("processing_tier") == "fast"
                    and meta.get("source") == "realtime"
                ):
                    existing = r
                    break

            if existing is not None:
                existing.transcript_json = fast_json
                existing.transcript_md = fast_md
                meta = dict(existing.meta) if isinstance(existing.meta, dict) else {}
                meta["fast_snapshot_seq"] = snapshot_seq
                existing.meta = meta
                fast_row_id = existing.id
            else:
                last_rev = (
                    db.query(Transcript.revision)
                    .filter(Transcript.conversation_id == cid)
                    .order_by(Transcript.revision.desc())
                    .limit(1)
                    .scalar()
                )
                fast_revision = int(last_rev or 0) + 1
                fast_row = Transcript(
                    conversation_id=cid,
                    user_id=uid,
                    revision=fast_revision,
                    kind="asr",
                    status="success",
                    meta={
                        "processing_tier": "fast",
                        "source": "realtime",
                        "fast_snapshot_seq": snapshot_seq,
                    },
                    transcript_json=fast_json,
                    transcript_md=fast_md,
                )
                db.add(fast_row)
                db.flush()
                fast_row_id = fast_row.id

            if not _has_non_fast_final_row(db, cid, uid):
                conv.active_transcript_id = fast_row_id

        storage.upload_transcript_json(fast_json, user_id, conversation_id, encrypt=True)
        storage.upload_transcript_markdown(fast_md, user_id, conversation_id, encrypt=True)
        logger.debug(
            "Realtime fast snapshot persisted conversation=%s seq=%s",
            conversation_id,
            snapshot_seq,
        )
        return True
    except Exception as e:
        logger.exception("persist_fast_snapshot failed: %s", e)
        return False


def finalize_realtime_session(
    *,
    user_id: str,
    conversation_id: str,
    language: str | None,
    pcm_mono_s16le: bytes,
    raw_container_bytes: bytes,
    partial_texts: list[str] | list[dict],
    finalize_id: str,
    prefer_pcm: bool,
    step_s: float | None = None,
    overlap_s: float | None = None,
) -> tuple[bool, str]:
    """
    Загружает WAV или WebM в S3, создаёт строку transcript (fast, success),
    ставит Celery transcribe_file с meta processing_tier=final.

    Возвращает (True, "") при успехе или (False, reason).
    """
    uid = UUID(user_id)
    cid = UUID(conversation_id)

    audio_bytes: bytes | None = None
    audio_ext: str = "webm"

    if prefer_pcm and len(pcm_mono_s16le) >= MIN_REALTIME_FINALIZE_PCM_BYTES:
        audio_bytes = pcm_s16le_mono_to_wav(bytes(pcm_mono_s16le), 16_000)
        audio_ext = "wav"
    elif len(raw_container_bytes) >= MIN_AUDIO_CONTENT_BYTES:
        audio_bytes = bytes(raw_container_bytes)
        audio_ext = "webm"
    elif len(pcm_mono_s16le) >= MIN_REALTIME_FINALIZE_PCM_BYTES:
        audio_bytes = pcm_s16le_mono_to_wav(bytes(pcm_mono_s16le), 16_000)
        audio_ext = "wav"

    if not audio_bytes:
        return False, "insufficient_audio"

    fast_segments = _fast_segments_from_partials(
        partial_texts,
        len(pcm_mono_s16le),
        16_000,
        step_s=step_s,
        overlap_s=overlap_s,
    )
    fast_json = {"segments": fast_segments}

    try:
        storage.upload_audio(
            audio_bytes,
            user_id,
            conversation_id,
            audio_object_ext=audio_ext,
            encrypt=True,
        )

        fast_revision = 0
        fast_row_id: int | None = None

        with session_scope() as db:
            conv = (
                db.query(Conversation)
                .filter(Conversation.id == cid, Conversation.user_id == uid)
                .with_for_update()
                .first()
            )
            if conv is None:
                return False, "conversation_not_found"

            conv.audio_object_ext = audio_ext
            conv.audio_uploaded_at = datetime.now(timezone.utc)

            last_rev = (
                db.query(Transcript.revision)
                .filter(Transcript.conversation_id == cid)
                .order_by(Transcript.revision.desc())
                .limit(1)
                .scalar()
            )
            fast_revision = int(last_rev or 0) + 1

            fast_md = _segments_to_md(fast_segments)
            fast_row = Transcript(
                conversation_id=cid,
                user_id=uid,
                revision=fast_revision,
                kind="asr",
                status="success",
                meta={
                    "processing_tier": "fast",
                    "source": "realtime",
                    "finalize_id": finalize_id,
                    "audio_object_ext": audio_ext,
                },
                transcript_json=fast_json,
                transcript_md=fast_md,
            )
            db.add(fast_row)
            db.flush()
            fast_row_id = fast_row.id

            conv.active_transcript_id = fast_row_id

        storage.upload_transcript_json(fast_json, user_id, conversation_id, encrypt=True)
        storage.upload_transcript_markdown(fast_md, user_id, conversation_id, encrypt=True)

        celery_app.send_task(
            "workers.tasks.asr.transcribe_file",
            args=[user_id, conversation_id],
            kwargs={
                "language": language,
                "audio_object_ext": audio_ext,
                "transcript_meta_extra": {
                    "processing_tier": "final",
                    "source": "realtime",
                    "finalize_id": finalize_id,
                    "related_fast_revision": fast_revision,
                },
            },
            queue="asr_final",
        )

        logger.info(
            "Realtime finalize: queued final ASR conversation=%s finalize_id=%s fast_revision=%s",
            conversation_id,
            finalize_id,
            fast_revision,
        )
        return True, ""

    except Exception as e:
        logger.exception("finalize_realtime_session failed: %s", e)
        return False, "server_error"
