"""
ASR transcription tasks.
"""

from __future__ import annotations

import os
import tempfile
import wave
from pathlib import Path
from uuid import UUID

from app.models import Conversation, Transcript, User
from app.services.pipeline_event_write import record_pipeline_event

from ..celery_app import asr_slice_queue, celery_app
from celery import chain, chord  # type: ignore
from sqlalchemy import func, update
from core.asr_chunk import transcribe_audio_chunk_bytes
from core.audio_format import MIN_AUDIO_CONTENT_BYTES
from core.config import app_config
from core.db import session_scope
from core.logging import logger
from core.s3 import storage
from core.webm_pcm import ffmpeg_binary
from plugins.loader import plugin_registry
from workers.tasks.embeddings import schedule_transcript_embedding
from workers.tasks.llm import schedule_recording_session_summary

STUB_TRANSCRIPT: dict = {
    "segments": [
        {
            "speaker": "Speaker 1",
            "start": 0.0,
            "end": 1.0,
            "text": "[stub ASR] No provider configured; placeholder transcript (Phase A).",
        }
    ]
}


def _transcript_to_markdown(data: dict) -> str:
    lines: list[str] = []
    for seg in data.get("segments") or []:
        sp = seg.get("speaker", "Speaker 1")
        lines.append(
            f"**{sp}** ({float(seg.get('start', 0)):.1f}s–{float(seg.get('end', 0)):.1f}s): "
            f"{seg.get('text', '')}"
        )
    return "\n\n".join(lines) if lines else "_No transcript._\n"


def _wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
    return float(frames) / float(rate) if rate else 0.0


def _slice_wav(src_wav: Path, start_s: float, end_s: float) -> Path:
    exe = ffmpeg_binary()
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH (set VT_FFMPEG_PATH)")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    out = Path(tmp.name)
    try:
        import subprocess

        subprocess.run(
            [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{max(0.0, float(start_s)):.3f}",
                "-to",
                f"{max(0.0, float(end_s)):.3f}",
                "-i",
                str(src_wav),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                str(out),
            ],
            check=True,
            capture_output=True,
            timeout=3600,
        )
        return out
    except Exception:
        out.unlink(missing_ok=True)
        raise


def _slice_media_to_wav_16k_mono(src_media: Path, start_s: float, end_s: float) -> Path:
    """Slice arbitrary media into a wav(16k mono) window via ffmpeg."""
    exe = ffmpeg_binary()
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH (set VT_FFMPEG_PATH)")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    out = Path(tmp.name)
    try:
        import subprocess

        subprocess.run(
            [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{max(0.0, float(start_s)):.3f}",
                "-to",
                f"{max(0.0, float(end_s)):.3f}",
                "-i",
                str(src_media),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                str(out),
            ],
            check=True,
            capture_output=True,
            timeout=3600,
        )
        return out
    except Exception:
        out.unlink(missing_ok=True)
        raise


@celery_app.task(name="workers.tasks.asr.record_asr_chunk_done", bind=True)
def record_asr_chunk_done(self, *, transcript_id: int) -> None:
    """Increment completed parallel ASR slice count (atomic; no transcript text)."""
    tid = int(transcript_id)
    with session_scope() as db:
        db.execute(
            update(Transcript)
            .where(Transcript.id == tid)
            .values(
                asr_chunk_completed=func.least(
                    func.coalesce(Transcript.asr_chunk_total, 0),
                    func.coalesce(Transcript.asr_chunk_completed, 0) + 1,
                )
            )
        )


@celery_app.task(name="workers.tasks.asr.transcribe_slice", bind=True)
def transcribe_slice(
    self,
    user_id: str,
    conversation_id: str,
    *,
    language: str | None,
    audio_object_ext: str,
    start_s: float,
    end_s: float,
    trim_before_s: float | None = None,
) -> dict:
    """
    Transcribe a time slice of the conversation audio (final/upload chunking).
    Returns {"ok": bool, "segments": list[dict], "error": str|None}.
    """
    ext = (audio_object_ext or "webm").lower().lstrip(".")
    tmp_path: Path | None = None
    wav_clip: Path | None = None
    vad_prefs: dict | None = None
    try:
        user_uuid = UUID(user_id)
        with session_scope() as db:
            u = db.query(User).filter(User.id == user_uuid).first()
            if u is not None and isinstance(u.preferences, dict):
                vad_prefs = u.preferences

        audio_data = storage.download_audio(
            user_id, conversation_id, audio_object_ext=ext, decrypt=True
        )
        if len(audio_data) < MIN_AUDIO_CONTENT_BYTES:
            return {"ok": False, "segments": [], "error": "audio_too_small"}

        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_path.write_bytes(audio_data)

        wav_clip = _slice_media_to_wav_16k_mono(tmp_path, float(start_s), float(end_s))
        provider = plugin_registry.get_asr_provider(tier="final")
        if provider is None:
            return {"ok": False, "segments": [], "error": "no_asr_provider"}
        segs = provider.transcribe(str(wav_clip), language=language, vad_preferences=vad_prefs)

        out: list[dict] = []
        for seg in segs:
            d = seg.to_dict() if hasattr(seg, "to_dict") else seg
            try:
                st = float(d.get("start", 0.0)) + float(start_s)
                en = float(d.get("end", 0.0)) + float(start_s)
            except Exception:
                continue
            if trim_before_s is not None and en <= float(trim_before_s):
                continue
            dd = dict(d)
            dd["start"] = st
            dd["end"] = en
            out.append(dd)
        return {"ok": True, "segments": out, "error": None}
    except Exception as e:
        return {"ok": False, "segments": [], "error": str(e)[:500]}
    finally:
        if wav_clip is not None:
            wav_clip.unlink(missing_ok=True)
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


@celery_app.task(name="workers.tasks.asr.finalize_parallel_transcript", bind=True)
def finalize_parallel_transcript(
    self,
    results: list[dict],
    *,
    user_id: str,
    conversation_id: str,
    transcript_id: int,
) -> dict:
    """
    Merge chunk transcription results, persist to S3/DB, promote to active, and queue diarization.
    """
    conv_uuid = UUID(conversation_id)
    user_uuid = UUID(user_id)

    errs = [r.get("error") for r in (results or []) if not r.get("ok")]
    if errs:
        msg = "; ".join(str(e) for e in errs if e)
        with session_scope() as db:
            row = (
                db.query(Transcript)
                .filter(
                    Transcript.id == int(transcript_id),
                    Transcript.conversation_id == conv_uuid,
                    Transcript.user_id == user_uuid,
                )
                .first()
            )
            if row is not None:
                row.status = "failed"
                row.meta = {**(row.meta or {}), "error": msg[:1000]}
                row.asr_chunk_total = None
                row.asr_chunk_completed = None
                record_pipeline_event(
                    db,
                    conversation_id=conv_uuid,
                    event_type="asr_failed",
                    transcript_id=int(transcript_id),
                    detail={"reason_code": "parallel_chunk_errors"},
                )
        return {"status": "failed", "error": msg[:1000]}

    merged: list[dict] = []
    for r in results or []:
        segs = r.get("segments") or []
        if isinstance(segs, list):
            for s in segs:
                if isinstance(s, dict):
                    merged.append(s)
    merged.sort(key=lambda x: float(x.get("start", 0.0)))
    transcript = {"segments": merged}
    md = _transcript_to_markdown(transcript)

    storage.upload_transcript_json(transcript, user_id, conversation_id, encrypt=True)
    storage.upload_transcript_markdown(md, user_id, conversation_id, encrypt=True)

    promoted_tid: int | None = None
    with session_scope() as db:
        row = (
            db.query(Transcript)
            .filter(
                Transcript.id == int(transcript_id),
                Transcript.conversation_id == conv_uuid,
                Transcript.user_id == user_uuid,
            )
            .first()
        )
        if row is None:
            raise RuntimeError("Transcript row missing for parallel finalize")
        row.transcript_json = transcript
        row.transcript_md = md
        row.status = "success"
        row.asr_chunk_total = None
        row.asr_chunk_completed = None
        record_pipeline_event(
            db,
            conversation_id=conv_uuid,
            event_type="asr_completed",
            transcript_id=int(transcript_id),
            detail={"transcript_id": int(transcript_id)},
        )

        conv = db.query(Conversation).filter(Conversation.id == conv_uuid).first()
        if conv is not None:
            conv.active_transcript_id = row.id
        promoted_tid = row.id

    if promoted_tid is not None:
        schedule_transcript_embedding(promoted_tid)

    if app_config.diarization.enabled:
        celery_app.send_task(
            "workers.tasks.diarization.run_diarization",
            args=[user_id, conversation_id],
            queue="diarization",
        )
    else:
        with session_scope() as db:
            conv_row = db.query(Conversation).filter(Conversation.id == conv_uuid).first()
            rsid = str(conv_row.recording_session_id) if conv_row else conversation_id
        schedule_recording_session_summary(user_id, rsid)

    return {"status": "success", "segments_count": len(merged)}


@celery_app.task(name="workers.tasks.asr.transcribe_file", bind=True)
def transcribe_file(
    self,
    user_id: str,
    conversation_id: str,
    language: str | None = None,
    audio_object_ext: str = "webm",
    transcript_meta_extra: dict | None = None,
) -> dict:
    """
    Transcribe an audio file using the configured ASR provider, or stub (Phase A).
    """
    ext = (audio_object_ext or "webm").lower().lstrip(".")
    logger.info(
        "Starting ASR transcription for conversation %s (audio_object_ext=%s)",
        conversation_id,
        ext,
    )

    tmp_path: Path | None = None
    vad_prefs: dict | None = None
    try:
        conv_uuid = UUID(conversation_id)
        user_uuid = UUID(user_id)

        with session_scope() as db:
            u = db.query(User).filter(User.id == user_uuid).first()
            if u is not None and isinstance(u.preferences, dict):
                vad_prefs = u.preferences

        # Create a new transcript version row (pending -> running -> success/failed).
        with session_scope() as db:
            conv = (
                db.query(Conversation)
                .filter(Conversation.id == conv_uuid)
                .with_for_update()
                .first()
            )
            if conv is None:
                raise RuntimeError(f"Conversation not found: {conversation_id}")

            last_rev = (
                db.query(Transcript.revision)
                .filter(Transcript.conversation_id == conv_uuid)
                .order_by(Transcript.revision.desc())
                .limit(1)
                .scalar()
            )
            next_rev = int(last_rev or 0) + 1

            meta_base: dict = {
                "asr_provider": getattr(
                    plugin_registry.get_asr_provider(tier="final"), "name", None
                )
                if plugin_registry.get_asr_provider(tier="final")
                else None,
                "language_hint": language,
                "audio_object_ext": ext,
            }
            if transcript_meta_extra:
                meta_base.update(dict(transcript_meta_extra))

            trow = Transcript(
                conversation_id=conv_uuid,
                user_id=user_uuid,
                revision=next_rev,
                kind="asr",
                status="running",
                meta=meta_base,
            )
            db.add(trow)
            db.flush()  # allocate trow.id
            trow_id = int(trow.id)
            record_pipeline_event(
                db,
                conversation_id=conv_uuid,
                event_type="asr_started",
                transcript_id=trow_id,
                detail={"transcript_id": trow_id},
            )

        audio_data = storage.download_audio(
            user_id, conversation_id, audio_object_ext=ext, decrypt=True
        )
        if len(audio_data) < MIN_AUDIO_CONTENT_BYTES:
            raise RuntimeError(
                f"Audio too small ({len(audio_data)} B) for conversation {conversation_id}; "
                "object in S3 is likely corrupt or truncated. Re-upload. "
                "If decrypt is wrong, ensure API and worker use the same VT_JWT_SECRET."
            )

        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_path.write_bytes(audio_data)

        provider = plugin_registry.get_asr_provider(tier="final")
        if provider:
            # Normalize input container → wav to avoid fragmented WebM edge-cases
            # (browser MediaRecorder chunks concatenation may produce non-seekable/cued WebM).
            from app.asr.audio_util import media_to_wav_16k_mono

            wav_path = None
            try:
                wav_path = media_to_wav_16k_mono(tmp_path)
                meta = meta_base
                processing_tier = str(meta.get("processing_tier") or "").strip().lower()
                source = str(meta.get("source") or "").strip().lower()

                # Long upload optimization (ТЗ §17): chunk by time and merge with offsets.
                # Default chunking is enabled only for final/upload-like work.
                chunk_s_env = (str(meta.get("chunk_seconds") or "") or "").strip()
                if not chunk_s_env:
                    chunk_s_env = (os.environ.get("VT_ASR_CHUNK_SECONDS") or "").strip()
                overlap_s_env = (os.environ.get("VT_ASR_CHUNK_OVERLAP_SECONDS") or "").strip()

                do_chunk = False
                try:
                    chunk_s = float(chunk_s_env) if chunk_s_env else 0.0
                except ValueError:
                    chunk_s = 0.0
                try:
                    overlap_s = float(overlap_s_env) if overlap_s_env else 1.0
                except ValueError:
                    overlap_s = 1.0
                if processing_tier == "final" and source in ("upload", "retranscribe", "realtime"):
                    do_chunk = chunk_s >= 30.0  # guard: don't chunk into too small slices

                # Parallel chunking: split into Celery tasks and merge via chord (requires result backend).
                parallel = os.environ.get("VT_ASR_PARALLEL_CHUNKS", "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                )

                if do_chunk and parallel:
                    dur = _wav_duration_seconds(wav_path)
                    if dur > (chunk_s + 1.0):
                        logger.info(
                            "ASR parallel chunking enabled: dur=%.3fs chunk=%.1fs overlap=%.2fs",
                            dur,
                            chunk_s,
                            overlap_s,
                        )
                        meta["chunk_seconds"] = chunk_s
                        meta["chunk_overlap_seconds"] = overlap_s
                        meta["parallel_chunks"] = True

                        header = []
                        t0 = 0.0
                        idx = 0
                        while t0 < dur:
                            s0 = max(0.0, t0 - overlap_s if idx > 0 else 0.0)
                            s1 = min(
                                dur,
                                t0
                                + chunk_s
                                + (overlap_s if (t0 + chunk_s) < dur else 0.0),
                            )
                            slice_sig = transcribe_slice.s(
                                user_id,
                                conversation_id,
                                language=language,
                                audio_object_ext=ext,
                                start_s=float(s0),
                                end_s=float(s1),
                                trim_before_s=(float(t0) if idx > 0 else None),
                            ).set(queue=asr_slice_queue())
                            bump_sig = record_asr_chunk_done.si(transcript_id=trow_id).set(
                                queue="asr_final"
                            )
                            header.append(chain(slice_sig, bump_sig))
                            idx += 1
                            t0 += chunk_s

                        with session_scope() as db:
                            row = (
                                db.query(Transcript)
                                .filter(
                                    Transcript.id == trow_id,
                                    Transcript.conversation_id == conv_uuid,
                                    Transcript.user_id == user_uuid,
                                )
                                .first()
                            )
                            if row is not None:
                                row.meta = dict(meta)
                                row.asr_chunk_total = len(header)
                                row.asr_chunk_completed = 0

                        body = celery_app.signature(
                            "workers.tasks.asr.finalize_parallel_transcript",
                            kwargs={
                                "user_id": user_id,
                                "conversation_id": conversation_id,
                                "transcript_id": trow_id,
                            },
                            queue="asr_final",
                        )
                        chord(header)(body)
                        # Important: return without marking row successful — callback will do it.
                        return {"status": "running", "mode": "parallel_chunks", "chunks": len(header)}

                if do_chunk:
                    dur = _wav_duration_seconds(wav_path)
                    if dur > (chunk_s + 1.0):
                        logger.info(
                            "ASR chunking enabled: dur=%.3fs chunk=%.1fs overlap=%.2fs",
                            dur,
                            chunk_s,
                            overlap_s,
                        )
                        # Record actual settings for observability.
                        meta["chunk_seconds"] = chunk_s
                        meta["chunk_overlap_seconds"] = overlap_s

                        n_chunks = 0
                        tv = 0.0
                        while tv < dur:
                            n_chunks += 1
                            tv += chunk_s
                        with session_scope() as db:
                            r2 = (
                                db.query(Transcript)
                                .filter(
                                    Transcript.id == trow_id,
                                    Transcript.conversation_id == conv_uuid,
                                    Transcript.user_id == user_uuid,
                                )
                                .first()
                            )
                            if r2 is not None:
                                prev = dict(r2.meta or {})
                                prev.update(
                                    {
                                        k: meta[k]
                                        for k in ("chunk_seconds", "chunk_overlap_seconds")
                                        if k in meta
                                    }
                                )
                                r2.meta = prev
                                r2.asr_chunk_total = n_chunks
                                r2.asr_chunk_completed = 0

                        merged_segments: list = []
                        t0 = 0.0
                        idx = 0
                        while t0 < dur:
                            # Slice window with overlap
                            s0 = max(0.0, t0 - overlap_s if idx > 0 else 0.0)
                            s1 = min(dur, t0 + chunk_s + (overlap_s if (t0 + chunk_s) < dur else 0.0))
                            clip = None
                            try:
                                clip = _slice_wav(wav_path, s0, s1)
                                segs = provider.transcribe(
                                    str(clip), language=language, vad_preferences=vad_prefs
                                )
                            finally:
                                if clip is not None:
                                    clip.unlink(missing_ok=True)

                            # Offset and trim overlap duplicates.
                            for seg in segs:
                                d = seg.to_dict() if hasattr(seg, "to_dict") else seg
                                try:
                                    st = float(d.get("start", 0.0)) + float(s0)
                                    en = float(d.get("end", 0.0)) + float(s0)
                                except Exception:
                                    continue
                                # Drop anything that ends before the hard boundary t0 on subsequent chunks.
                                if idx > 0 and en <= t0:
                                    continue
                                d = dict(d)
                                d["start"] = st
                                d["end"] = en
                                merged_segments.append(d)

                            idx += 1
                            t0 += chunk_s
                            with session_scope() as db:
                                r2 = (
                                    db.query(Transcript)
                                    .filter(
                                        Transcript.id == trow_id,
                                        Transcript.conversation_id == conv_uuid,
                                        Transcript.user_id == user_uuid,
                                    )
                                    .first()
                                )
                                if r2 is not None and r2.asr_chunk_total:
                                    r2.asr_chunk_completed = min(
                                        int(r2.asr_chunk_total),
                                        int(r2.asr_chunk_completed or 0) + 1,
                                    )

                        merged_segments.sort(key=lambda x: float(x.get("start", 0.0)))
                        transcript = {"segments": merged_segments}
                    else:
                        segments = provider.transcribe(
                            str(wav_path), language=language, vad_preferences=vad_prefs
                        )
                        transcript = {
                            "segments": [
                                seg.to_dict() if hasattr(seg, "to_dict") else seg
                                for seg in segments
                            ]
                        }
                else:
                    segments = provider.transcribe(
                        str(wav_path), language=language, vad_preferences=vad_prefs
                    )
                    transcript = {
                        "segments": [
                            seg.to_dict() if hasattr(seg, "to_dict") else seg for seg in segments
                        ]
                    }
            finally:
                if wav_path is not None and wav_path.exists():
                    wav_path.unlink(missing_ok=True)
        else:
            logger.warning(
                "No ASR provider available; writing stub transcript (Phase A)"
            )
            transcript = dict(STUB_TRANSCRIPT)
            if language:
                transcript["segments"][0]["text"] = (
                    f"{transcript['segments'][0]['text']} (language hint: {language})"
                )

        md = _transcript_to_markdown(transcript)
        storage.upload_transcript_json(transcript, user_id, conversation_id, encrypt=True)
        storage.upload_transcript_markdown(md, user_id, conversation_id, encrypt=True)

        promoted_tid: int | None = None
        with session_scope() as db:
            # Load the transcript row we created earlier and mark it successful.
            row = (
                db.query(Transcript)
                .filter(
                    Transcript.conversation_id == conv_uuid,
                    Transcript.revision == next_rev,
                )
                .first()
            )
            if row is None:
                raise RuntimeError(
                    f"Transcript row missing (conversation={conversation_id} revision={next_rev})"
                )

            row.transcript_json = transcript
            row.transcript_md = md
            row.status = "success"
            row.asr_chunk_total = None
            row.asr_chunk_completed = None
            record_pipeline_event(
                db,
                conversation_id=conv_uuid,
                event_type="asr_completed",
                transcript_id=row.id,
                detail={"transcript_id": row.id},
            )

            conv = db.query(Conversation).filter(Conversation.id == conv_uuid).first()
            if conv is not None:
                conv.active_transcript_id = row.id
            promoted_tid = row.id

        if promoted_tid is not None:
            schedule_transcript_embedding(promoted_tid)

        seg_count = len(transcript.get("segments", []))
        logger.info(f"Completed ASR transcription for conversation {conversation_id}")
        if app_config.diarization.enabled:
            # Queue diarization as a separate post-processing step (Scheme 2 versioning).
            celery_app.send_task(
                "workers.tasks.diarization.run_diarization",
                args=[user_id, conversation_id],
            )
        else:
            with session_scope() as db:
                conv_row = db.query(Conversation).filter(Conversation.id == conv_uuid).first()
                rsid = str(conv_row.recording_session_id) if conv_row else conversation_id
            schedule_recording_session_summary(user_id, rsid)
        return {"status": "success", "segments_count": seg_count}

    except Exception as e:
        # Best-effort: mark the created transcript row as failed (if it exists).
        try:
            conv_uuid = UUID(conversation_id)
            with session_scope() as db:
                last = (
                    db.query(Transcript)
                    .filter(
                        Transcript.conversation_id == conv_uuid,
                        Transcript.kind == "asr",
                        Transcript.status == "running",
                    )
                    .order_by(Transcript.revision.desc())
                    .first()
                )
                if last is not None:
                    last.status = "failed"
                    last.asr_chunk_total = None
                    last.asr_chunk_completed = None
                    record_pipeline_event(
                        db,
                        conversation_id=conv_uuid,
                        event_type="asr_failed",
                        transcript_id=last.id,
                        detail={"reason_code": "exception"},
                    )
        except Exception:
            pass
        logger.error(f"ASR transcription failed for {conversation_id}: {e}")
        raise
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


@celery_app.task(name="workers.tasks.asr.transcribe_chunk", bind=True)
def transcribe_chunk(
    self, audio_data: bytes, language: str | None = None
) -> str:
    """
    Transcribe a small audio chunk (for realtime mode).
    """
    return transcribe_audio_chunk_bytes(audio_data, language=language)
