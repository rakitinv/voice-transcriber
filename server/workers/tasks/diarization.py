"""
Speaker diarization tasks.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import UUID

from app.models import Conversation, Transcript, User
from app.services.pipeline_error_classify import pipeline_failure_detail
from app.services.pipeline_event_write import record_pipeline_event

from ..celery_app import celery_app
from core.audio_format import MIN_AUDIO_CONTENT_BYTES
from core.db import session_scope
from core.diarization_prefs import effective_turn_level_retranscription
from core.logging import logger
from core.s3 import storage
from core.webm_pcm import ffmpeg_binary
from plugins.loader import plugin_registry
from core.speaker_labels import normalize_diarization_segments, rebuild_transcript_md
from app.services.speaker_display import reset_speaker_labels_on_diarization_rerun
from workers.tasks.embeddings import schedule_transcript_embedding
from workers.tasks.llm import schedule_post_diarization_pipeline


def _language_hint_from_transcript_json(tjson: dict | None) -> str | None:
    if not tjson:
        return None
    segs = tjson.get("segments") or []
    if not isinstance(segs, list) or not segs:
        return None
    first = segs[0] if isinstance(segs[0], dict) else {}
    raw = str(first.get("language", "")).strip().lower()
    if not raw or raw in ("auto", "—", "-"):
        return None
    return raw


def _slice_wav_16k_mono(src_wav: Path, start_s: float, end_s: float) -> Path:
    """
    Slice an existing wav into a smaller wav (16k mono) using ffmpeg.
    Caller must delete the returned file.
    """
    exe = ffmpeg_binary()
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH (set VT_FFMPEG_PATH)")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    out = Path(tmp.name)
    try:
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
            timeout=600,
        )
    except Exception:
        if out.exists():
            out.unlink(missing_ok=True)
        raise
    return out


def _slice_wav_16k_mono_in_memory(
    wav_path: Path, start_s: float, end_s: float
) -> Path | None:
    """
    Fast path: slice a 16kHz mono wav in memory and write a temp wav.

    Avoids spawning ffmpeg for every diarization turn, which is a major overhead
    on short conversations with multiple turns.

    Returns None if required deps are unavailable or the file isn't 16k mono.
    """
    try:
        import numpy as np  # type: ignore
        import soundfile as sf  # type: ignore
    except Exception:
        return None

    try:
        data, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    except Exception:
        return None
    if sr != 16000:
        return None
    # mono expected; if 2d treat as multi-channel and refuse
    if hasattr(data, "ndim") and getattr(data, "ndim", 1) != 1:
        return None

    n = int(getattr(data, "shape", [0])[0] if hasattr(data, "shape") else len(data))
    s0 = max(0, min(n, int(round(float(start_s) * sr))))
    s1 = max(0, min(n, int(round(float(end_s) * sr))))
    if s1 <= s0:
        return None

    clip = data[s0:s1]
    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    out = Path(out_path)
    try:
        sf.write(str(out), np.asarray(clip, dtype="float32"), sr, subtype="PCM_16")
        return out
    except Exception:
        out.unlink(missing_ok=True)
        return None


def _default_language_hint_from_user(user: User) -> str | None:
    prefs = user.preferences if isinstance(user.preferences, dict) else {}
    raw = str(prefs.get("default_language", "")).strip().lower()
    if not raw or raw in ("auto", "—", "-"):
        return None
    return raw


def _merge_turns(turns: list, *, gap_s: float) -> list[tuple[float, float, str]]:
    """
    Merge adjacent diarization turns of the same speaker if gap is small.

    This reduces ASR calls and makes transcripts more stable on rapid dialog.
    """
    merged: list[tuple[float, float, str]] = []
    # Normalize & sort by start
    norm: list[tuple[float, float, str]] = []
    for t in turns:
        t0 = float(getattr(t, "start", 0.0))
        t1 = float(getattr(t, "end", 0.0))
        if t1 <= t0:
            continue
        sp = str(getattr(t, "speaker", "Speaker 1"))
        norm.append((t0, t1, sp))
    norm.sort(key=lambda x: x[0])

    for t0, t1, sp in norm:
        if not merged:
            merged.append((t0, t1, sp))
            continue
        p0, p1, psp = merged[-1]
        if sp == psp and (t0 - p1) <= gap_s:
            merged[-1] = (p0, max(p1, t1), psp)
        else:
            merged.append((t0, t1, sp))
    return merged


@celery_app.task(name="workers.tasks.diarization.run_diarization", bind=True)
def run_diarization(
    self, user_id: str, conversation_id: str
) -> dict:
    """
    Run speaker diarization on a conversation.

    Args:
        user_id: User ID
        conversation_id: Conversation ID

    Returns:
        Dictionary with diarization result
    """
    t_total0 = time.perf_counter()
    logger.info(f"Starting diarization for conversation {conversation_id}")

    try:
        conv_uuid = UUID(conversation_id)
        user_uuid = UUID(user_id)
        base_transcript_json: dict | None = None
        base_transcript_id: int | None = None
        base_transcript_revision: int | None = None
        user_settings_lang: str | None = None
        user_vad_prefs: dict | None = None
        user_turn_level_retranscription: bool = False

        # Allocate a new transcript revision for diarized output.
        with session_scope() as db:
            user = db.query(User).filter(User.id == user_uuid).first()
            if user is not None:
                user_settings_lang = _default_language_hint_from_user(user)
                if isinstance(user.preferences, dict):
                    user_vad_prefs = user.preferences
                # Compute effective preference while `user` is bound to the session.
                user_turn_level_retranscription = effective_turn_level_retranscription(user)
            else:
                user_turn_level_retranscription = effective_turn_level_retranscription(None)

            conv = (
                db.query(Conversation)
                .filter(Conversation.id == conv_uuid)
                .with_for_update()
                .first()
            )
            if conv is None:
                raise RuntimeError(f"Conversation not found: {conversation_id}")

            reset_speaker_labels_on_diarization_rerun(conv)

            # Load input transcript from active version (fallback to latest success).
            base_row = None
            if conv.active_transcript_id is not None:
                base_row = (
                    db.query(Transcript)
                    .filter(
                        Transcript.id == conv.active_transcript_id,
                        Transcript.conversation_id == conv_uuid,
                        Transcript.user_id == user_uuid,
                        Transcript.status == "success",
                    )
                    .first()
                )
            if base_row is None:
                base_row = (
                    db.query(Transcript)
                    .filter(
                        Transcript.conversation_id == conv_uuid,
                        Transcript.user_id == user_uuid,
                        Transcript.status == "success",
                    )
                    .order_by(Transcript.revision.desc())
                    .first()
                )

            if base_row is None or not base_row.transcript_json:
                raise RuntimeError("No successful transcript found to diarize")
            base_transcript_json = dict(base_row.transcript_json)
            base_transcript_id = base_row.id
            base_transcript_revision = base_row.revision

            last_rev = (
                db.query(Transcript.revision)
                .filter(Transcript.conversation_id == conv_uuid)
                .order_by(Transcript.revision.desc())
                .limit(1)
                .scalar()
            )
            next_rev = int(last_rev or 0) + 1

            out_row = Transcript(
                conversation_id=conv_uuid,
                user_id=user_uuid,
                revision=next_rev,
                kind="asr_diarized",
                status="running",
                meta={
                    "source_transcript_id": base_transcript_id,
                    "source_revision": base_transcript_revision,
                    "diarization_provider": "pyannote",
                    "device": (plugin_registry.get_diarization_provider().config.get("device")  # type: ignore[union-attr]
                               if plugin_registry.get_diarization_provider()
                               else None),
                },
            )
            db.add(out_row)
            db.flush()
            record_pipeline_event(
                db,
                conversation_id=conv_uuid,
                event_type="diarization_started",
                transcript_id=int(out_row.id),
                detail={"transcript_id": int(out_row.id), "revision": next_rev},
            )

        with session_scope() as db:
            conv = (
                db.query(Conversation)
                .filter(Conversation.id == UUID(conversation_id))
                .first()
            )
            ext = (conv.audio_object_ext if conv else None) or "webm"
        ext = ext.lower().lstrip(".")

        # Download audio (still in S3) and load transcript from DB (base_row above)
        audio_data = storage.download_audio(
            user_id, conversation_id, audio_object_ext=ext, decrypt=True
        )
        if len(audio_data) < MIN_AUDIO_CONTENT_BYTES:
            raise RuntimeError(
                f"Audio too small ({len(audio_data)} B) for diarization conversation {conversation_id}"
            )
        transcript = dict(base_transcript_json or {"segments": []})

        # Save audio to temporary file
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_path.write_bytes(audio_data)

        try:
            provider = plugin_registry.get_diarization_provider()
            if provider is None:
                raise RuntimeError("No diarization provider configured/loaded")

            t_py0 = time.perf_counter()
            turns = provider.run(
                str(tmp_path), transcript_segments=transcript.get("segments") or []
            )
            t_py1 = time.perf_counter()
            logger.info(
                "Diarization turns computed in %.3fs (turns=%s)",
                (t_py1 - t_py0),
                (len(turns) if turns else 0),
            )

            # Turn-level re-ASR when enabled (server YAML + user override) and ASR+ffmpeg exist;
            # otherwise keep ASR segment text and assign speakers by overlap with pyannote turns.
            diarized_segments = []
            asr = plugin_registry.get_asr_provider(tier="final")
            # For re-transcription inside diarization we prefer the user's explicit language setting
            # (it is usually more reliable than short-turn autodetection).
            lang_hint = user_settings_lang or _language_hint_from_transcript_json(transcript)
            asr_and_ffmpeg = asr is not None and ffmpeg_binary() is not None
            do_turn_level_re_asr = asr_and_ffmpeg and user_turn_level_retranscription
            min_turn_s = float(os.environ.get("VT_DIARIZATION_MIN_TURN_SECONDS", "0.3"))
            pad_default_s = float(os.environ.get("VT_DIARIZATION_TURN_PAD_SECONDS", "0.8"))
            # Asymmetric padding reduces cross-speaker bleed on fast dialog:
            # we want extra audio BEFORE the turn (avoid cutting first phonemes),
            # but minimal audio AFTER the turn (avoid capturing next speaker).
            pad_before_s = float(os.environ.get("VT_DIARIZATION_TURN_PAD_BEFORE_SECONDS", str(pad_default_s)))
            pad_after_s = float(os.environ.get("VT_DIARIZATION_TURN_PAD_AFTER_SECONDS", "0.15"))
            merge_gap_s = float(os.environ.get("VT_DIARIZATION_MERGE_GAP_SECONDS", "0.35"))

            if do_turn_level_re_asr and turns:
                from app.asr.audio_util import media_to_wav_16k_mono

                # Decode full audio once, then slice wav per turn for ASR.
                full_wav = None
                try:
                    t_wav0 = time.perf_counter()
                    full_wav = media_to_wav_16k_mono(tmp_path)
                    t_wav1 = time.perf_counter()
                    logger.info("Decoded full audio to wav in %.3fs", (t_wav1 - t_wav0))
                    merged_turns = _merge_turns(turns, gap_s=merge_gap_s)
                    logger.info("Merged turns: %s -> %s", len(turns), len(merged_turns))
                    t_asr_total = 0.0
                    t_slice_total = 0.0
                    for t0, t1, sp in merged_turns:
                        if (t1 - t0) < min_turn_s:
                            continue
                        clip = None
                        try:
                            # Add small padding: diarization turn boundaries are not exact and may cut off words.
                            s0 = max(0.0, t0 - pad_before_s)
                            s1 = t1 + pad_after_s
                            t_sl0 = time.perf_counter()
                            clip = _slice_wav_16k_mono_in_memory(full_wav, s0, s1)
                            if clip is None:
                                clip = _slice_wav_16k_mono(full_wav, s0, s1)
                            t_sl1 = time.perf_counter()
                            t_slice_total += (t_sl1 - t_sl0)

                            t_a0 = time.perf_counter()
                            segs = asr.transcribe(
                                str(clip),
                                language=lang_hint,
                                vad_preferences=user_vad_prefs,
                            )  # type: ignore[arg-type]
                            t_a1 = time.perf_counter()
                            t_asr_total += (t_a1 - t_a0)
                            text = " ".join((s.text or "").strip() for s in segs).strip()
                        finally:
                            if clip is not None and clip.exists():
                                clip.unlink(missing_ok=True)
                        if not text:
                            continue
                        diarized_segments.append(
                            {"speaker": sp, "start": t0, "end": t1, "text": text}
                        )
                    logger.info(
                        "Turn slicing time %.3fs; ASR time %.3fs; turns_out=%s",
                        t_slice_total,
                        t_asr_total,
                        len(diarized_segments),
                    )
                finally:
                    if full_wav is not None and full_wav.exists():
                        full_wav.unlink(missing_ok=True)
            else:
                # Merge transcript segments with diarization turns (segment-level max-overlap).
                for seg in transcript.get("segments", []):
                    s0 = float(seg.get("start", 0.0))
                    s1 = float(seg.get("end", 0.0))
                    best_sp = "Speaker 1"
                    best_ov = 0.0
                    for t in turns:
                        t0 = float(getattr(t, "start", 0.0))
                        t1 = float(getattr(t, "end", 0.0))
                        ov = max(0.0, min(s1, t1) - max(s0, t0))
                        if ov > best_ov:
                            best_ov = ov
                            best_sp = str(getattr(t, "speaker", best_sp))

                    diarized_segments.append(
                        {
                            "speaker": best_sp,
                            "start": s0,
                            "end": s1,
                            "text": seg.get("text", ""),
                        }
                    )

            # Update transcript with diarization (labels cleared at rerun start)
            transcript["segments"] = normalize_diarization_segments(diarized_segments, None)
            md = rebuild_transcript_md(transcript["segments"])

            promoted_tid: int | None = None
            with session_scope() as db:
                row = (
                    db.query(Transcript)
                    .filter(
                        Transcript.conversation_id == conv_uuid,
                        Transcript.revision == next_rev,
                        Transcript.kind == "asr_diarized",
                    )
                    .first()
                )
                if row is None:
                    raise RuntimeError(
                        f"Diarization transcript row missing (conversation={conversation_id} revision={next_rev})"
                    )
                row.transcript_json = transcript
                row.transcript_md = md
                row.status = "success"
                record_pipeline_event(
                    db,
                    conversation_id=conv_uuid,
                    event_type="diarization_completed",
                    transcript_id=row.id,
                    detail={"transcript_id": row.id, "revision": row.revision},
                )

                conv = db.query(Conversation).filter(Conversation.id == conv_uuid).first()
                if conv is not None:
                    conv.active_transcript_id = row.id
                promoted_tid = row.id

            if promoted_tid is not None:
                schedule_transcript_embedding(promoted_tid)

            with session_scope() as db:
                conv_row = db.query(Conversation).filter(Conversation.id == conv_uuid).first()
                rsid = str(conv_row.recording_session_id) if conv_row else conversation_id
            schedule_post_diarization_pipeline(user_id, conversation_id, rsid)

            logger.info(f"Completed diarization for conversation {conversation_id}")
            t_total1 = time.perf_counter()
            logger.info(
                "Diarization task total time %.3fs for conversation %s",
                (t_total1 - t_total0),
                conversation_id,
            )
            return {"status": "success", "speakers_count": 1}

        finally:
            tmp_path.unlink()

    except Exception as e:
        # Best-effort: mark latest running diarization row as failed.
        try:
            conv_uuid = UUID(conversation_id)
            with session_scope() as db:
                last = (
                    db.query(Transcript)
                    .filter(
                        Transcript.conversation_id == conv_uuid,
                        Transcript.kind == "asr_diarized",
                        Transcript.status == "running",
                    )
                    .order_by(Transcript.revision.desc())
                    .first()
                )
                if last is not None:
                    last.status = "failed"
                    meta = dict(last.meta) if isinstance(last.meta, dict) else {}
                    meta["diarization_error"] = str(e)
                    last.meta = meta
                    record_pipeline_event(
                        db,
                        conversation_id=conv_uuid,
                        event_type="diarization_failed",
                        transcript_id=last.id,
                        detail=pipeline_failure_detail(e, stage="diarization"),
                    )
        except Exception:
            pass
        logger.error(f"Diarization failed for {conversation_id}: {e}")
        raise
