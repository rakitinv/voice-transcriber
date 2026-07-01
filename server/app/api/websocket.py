"""
WebSocket: realtime audio и transcript (префикс приложения /ws, не /api).

Контракт: docs/WEBSOCKET.md
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from core.asr_chunk import transcribe_audio_chunk_bytes, transcribe_pcm_s16le_chunk
from core.audio_format import MIN_AUDIO_CONTENT_BYTES
from core.config import app_config
from core.db import get_db, session_scope
from core.logging import logger
from core.security import decode_access_token
from core.webm_pcm import FfmpegWebmPcmPipe, ffmpeg_binary
from ..models import Conversation, User
from .realtime_finalize import (
    MIN_REALTIME_FINALIZE_PCM_BYTES,
    finalize_realtime_session,
    persist_fast_snapshot,
)
from .ws_auth import extract_access_token_for_websocket
from .ws_hub import get_transcript_hub
from .ws_finalize_store import (
    mark_finalize_done,
    release_finalize_pending,
    try_claim_finalize_pending,
)
from .ws_realtime_buffer import (
    RealtimeAudioBuffer,
    RealtimeBufferParams,
    clamp_chunk_ms,
    resolve_realtime_mode,
)

router = APIRouter(prefix="/ws", tags=["websocket"])

_WS_CLOSE_POLICY = 1008  # Policy Violation — отказ в доступе / неверный токен


def _user_from_token(db: Session, token: str) -> User | None:
    payload = decode_access_token(token)
    if payload is None:
        return None
    sub = payload.get("sub")
    if sub is None:
        return None
    return db.query(User).filter(User.id == UUID(str(sub))).first()


def _use_pcm_pipeline() -> bool:
    if os.environ.get("VT_DISABLE_WEBM_DECODE", "").lower() in ("1", "true", "yes"):
        return False
    return ffmpeg_binary() is not None


def _default_language_hint(user: User) -> str | None:
    prefs = user.preferences if isinstance(user.preferences, dict) else {}
    raw = str(prefs.get("default_language", "")).strip().lower()
    if not raw or raw in ("auto", "—", "-"):
        return None
    return raw


async def _transcribe_pcm_chunk(
    pcm: bytes,
    language: str | None,
    vad_preferences: dict | None = None,
) -> str:
    return await asyncio.to_thread(
        transcribe_pcm_s16le_chunk,
        pcm,
        language,
        16_000,
        vad_preferences=vad_preferences,
    )


async def _transcribe_container_chunk(
    raw: bytes,
    language: str | None,
    vad_preferences: dict | None = None,
) -> str:
    return await asyncio.to_thread(
        transcribe_audio_chunk_bytes, raw, language, vad_preferences=vad_preferences
    )


def _autoprolong_limits_hit(pcm_len: int, raw_len: int, use_pcm: bool) -> tuple[bool, str]:
    """§7.2 — duration (PCM) or accumulated size; whichever binds."""
    lim = app_config.limits
    if raw_len >= lim.max_file_size_bytes:
        return True, "size"
    if use_pcm and pcm_len > 0:
        dur_s = float(pcm_len) / 32000.0  # s16le mono @ 16 kHz
        if dur_s >= float(lim.max_duration_seconds):
            return True, "duration"
    return False, ""


def _create_autoprolong_continuation_sync(prev_conv_id: UUID, user_uuid: UUID) -> dict | None:
    with session_scope() as db:
        prev = (
            db.query(Conversation)
            .filter(
                Conversation.id == prev_conv_id,
                Conversation.user_id == user_uuid,
                Conversation.deleted_at.is_(None),
            )
            .with_for_update()
            .first()
        )
        if prev is None:
            return None
        new_id = uuid4()
        s3_prefix = f"users/{user_uuid}/conversations/{new_id}"
        new_c = Conversation(
            id=new_id,
            user_id=user_uuid,
            title=prev.title,
            s3_prefix=s3_prefix,
            expires_at=prev.expires_at,
            recording_session_id=prev.recording_session_id,
            previous_conversation_id=prev.id,
            client_realtime_mode=prev.client_realtime_mode,
            client_chunk_ms=prev.client_chunk_ms,
            audio_object_ext=prev.audio_object_ext or "webm",
        )
        db.add(new_c)
        db.commit()
        return {
            "next_conversation_id": str(new_id),
            "recording_session_id": str(prev.recording_session_id),
            "previous_conversation_id": str(prev.id),
        }


def _build_buffer(conv: Conversation, *, pcm_sample_rate: int | None) -> RealtimeAudioBuffer:
    lim = app_config.limits
    mode = resolve_realtime_mode(
        conv.client_realtime_mode,
        lim.allowed_realtime_modes,
        lim.default_realtime_mode,
    )
    chunk_ms = clamp_chunk_ms(conv.client_chunk_ms, lim.chunk_ms_min, lim.chunk_ms_max)
    params = RealtimeBufferParams(
        mode=mode,
        chunk_ms=chunk_ms,
        max_window_ms=lim.max_window_ms,
        overlap_ms=lim.window_overlap_ms,
        pcm_sample_rate=pcm_sample_rate,
    )
    return RealtimeAudioBuffer(params)


def _stream_bytes_per_second(*, use_pcm: bool) -> float:
    return 32_000.0 if use_pcm else 16_000.0


def _piece_time_bounds(
    *,
    piece_len: int,
    stream_end_byte: int,
    bytes_per_second: float,
) -> tuple[float, float]:
    end_b = stream_end_byte
    start_b = max(0, end_b - piece_len)
    return start_b / bytes_per_second, end_b / bytes_per_second


def _append_partial_entry(partial_entries: list[dict], *, text: str, start: float, end: float) -> None:
    t = text.strip()
    if t:
        partial_entries.append({"start": start, "end": end, "text": t})


async def _transcribe_and_publish_pieces(
    *,
    pieces: list[bytes],
    partial_entries: list[dict],
    hub,
    cid_str: str,
    mode: str,
    use_pcm: bool,
    session_pcm: bytearray,
    session_raw: bytearray,
    bps: float,
    lang_hint: str | None,
    vad_prefs: dict | None,
    decoder: FfmpegWebmPcmPipe | None,
    final: bool = False,
) -> None:
    for piece in pieces:
        if not piece:
            continue
        try:
            text = (
                await _transcribe_pcm_chunk(piece, lang_hint, vad_prefs)
                if decoder is not None
                else await _transcribe_container_chunk(piece, lang_hint, vad_prefs)
            )
        except Exception as e:
            logger.exception("transcribe_chunk failed: %s", e)
            continue
        stream_end = len(session_pcm) if decoder is not None else len(session_raw)
        start_s, end_s = _piece_time_bounds(
            piece_len=len(piece),
            stream_end_byte=stream_end,
            bytes_per_second=bps,
        )
        _append_partial_entry(partial_entries, text=text, start=start_s, end=end_s)
        if not text.strip():
            continue
        await hub.publish(
            cid_str,
            {
                "type": "transcript_partial",
                "conversation_id": cid_str,
                "text": text,
                "start": start_s,
                "end": end_s,
                "realtime_mode": mode,
                "pcm": use_pcm,
                "final": final,
                "processing_tier": "fast",
            },
        )


async def _flush_tail_asr(
    *,
    decoder: FfmpegWebmPcmPipe | None,
    audio_buf: RealtimeAudioBuffer,
    session_pcm: bytearray,
    session_raw: bytearray,
    use_pcm: bool,
    mode: str,
    partial_entries: list[dict],
    hub,
    cid_str: str,
    lang_hint: str | None,
    vad_prefs: dict | None,
    bps: float,
    close_decoder: bool,
    final: bool,
) -> None:
    """Decode/ffmpeg flush + windowed tail — must run before finalize saves partial_entries."""
    pieces: list[bytes] = []
    if decoder is not None:
        if close_decoder:
            try:
                await asyncio.to_thread(decoder.close)
            except Exception:
                pass
        try:
            pcm = await asyncio.to_thread(decoder.drain_pcm)
        except Exception:
            pcm = b""
        if pcm:
            session_pcm.extend(pcm)
            pieces = audio_buf.feed(pcm)
    if not pieces and mode == "windowed":
        tail = getattr(audio_buf, "_buf", None)  # type: ignore[attr-defined]
        if isinstance(tail, (bytearray, bytes)) and len(tail) > 0:
            pieces = [bytes(tail)]
    await _transcribe_and_publish_pieces(
        pieces=pieces,
        partial_entries=partial_entries,
        hub=hub,
        cid_str=cid_str,
        mode=mode,
        use_pcm=use_pcm,
        session_pcm=session_pcm,
        session_raw=session_raw,
        bps=bps,
        lang_hint=lang_hint,
        vad_prefs=vad_prefs,
        decoder=decoder,
        final=final,
    )


async def _maybe_persist_fast_snapshot(
    *,
    user_id: str,
    conversation_id: str,
    partial_entries: list[dict],
    pcm_len: int,
    lim,
    last_persist_at: float,
    fast_snapshot_seq: int,
    hub,
    cid_str: str,
    step_s: float,
    overlap_s: float,
) -> tuple[float, int]:
    """Persist fast draft when interval and min audio duration are met."""
    if not partial_entries:
        return last_persist_at, fast_snapshot_seq
    pcm_dur = float(pcm_len) / 32000.0 if pcm_len > 0 else 0.0
    if pcm_dur < float(lim.fast_persist_min_audio_s):
        return last_persist_at, fast_snapshot_seq
    now = time.monotonic()
    if now - last_persist_at < float(lim.fast_persist_interval_s):
        return last_persist_at, fast_snapshot_seq

    seq = fast_snapshot_seq + 1
    ok = await asyncio.to_thread(
        persist_fast_snapshot,
        user_id=user_id,
        conversation_id=conversation_id,
        partial_texts=list(partial_entries),
        pcm_len=pcm_len,
        snapshot_seq=seq,
        step_s=step_s,
        overlap_s=overlap_s,
    )
    if not ok:
        return last_persist_at, fast_snapshot_seq

    await hub.publish(
        cid_str,
        {
            "type": "fast_snapshot",
            "conversation_id": cid_str,
            "fast_snapshot_seq": seq,
            "processing_tier": "fast",
        },
    )
    return now, seq


@router.websocket("/audio/{conversation_id}")
async def websocket_audio(
    websocket: WebSocket,
    conversation_id: UUID,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Поток аудио-чанков: WebM/Opus → PCM (ffmpeg) → буфер chunk/windowed по времени, ASR chunk.
    Без ffmpeg — сырой контейнер и оценка байт/с (legacy).
    Частичные тексты публикуются в TranscriptHub → /ws/transcript.
    """
    token, subproto, ws_reject = extract_access_token_for_websocket(websocket)
    if ws_reject:
        await websocket.close(code=_WS_CLOSE_POLICY, reason=ws_reject)
        return

    user = _user_from_token(db, token or "")
    if user is None:
        await websocket.close(code=_WS_CLOSE_POLICY, reason="invalid_token")
        return
    lang_hint = _default_language_hint(user)
    vad_prefs = user.preferences if isinstance(user.preferences, dict) else None

    conv = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )
    if conv is None:
        await websocket.close(code=_WS_CLOSE_POLICY, reason="forbidden_or_missing")
        return

    use_pcm = _use_pcm_pipeline()
    pcm_sr = 16_000 if use_pcm else None
    audio_buf = _build_buffer(conv, pcm_sample_rate=pcm_sr)
    hub = get_transcript_hub()
    cid_str = str(conversation_id)
    lim = app_config.limits
    mode = resolve_realtime_mode(
        conv.client_realtime_mode,
        lim.allowed_realtime_modes,
        lim.default_realtime_mode,
    )
    chunk_ms = clamp_chunk_ms(conv.client_chunk_ms, lim.chunk_ms_min, lim.chunk_ms_max)
    step_s = chunk_ms / 1000.0
    overlap_s = float(lim.window_overlap_ms) / 1000.0
    bps = _stream_bytes_per_second(use_pcm=use_pcm)

    decoder: FfmpegWebmPcmPipe | None = FfmpegWebmPcmPipe() if use_pcm else None

    await websocket.accept(subprotocol=subproto)
    await websocket.send_json(
        {
            "type": "ready",
            "channel": "audio",
            "conversation_id": cid_str,
            "realtime_mode": mode,
            "chunk_ms": clamp_chunk_ms(conv.client_chunk_ms, lim.chunk_ms_min, lim.chunk_ms_max),
            "pcm_pipeline": use_pcm,
            "message": (
                "Audio channel open; send binary WebM/Opus chunks (PCM decode via ffmpeg)."
                if use_pcm
                else "Audio channel open; ffmpeg unavailable — legacy byte-rate buffering."
            ),
        }
    )

    session_pcm = bytearray()
    session_raw = bytearray()
    partial_entries: list[dict] = []
    handoff_sent = False
    last_fast_persist_at = 0.0
    fast_snapshot_seq = 0
    decoder_tail_flushed = False

    try:
        while True:
            try:
                msg = await websocket.receive()
            except WebSocketDisconnect:
                logger.info("WS audio disconnected conversation_id=%s", conversation_id)
                break
            if msg.get("type") != "websocket.receive":
                break
            if "bytes" in msg:
                if decoder is not None:
                    try:
                        await asyncio.to_thread(decoder.write_webm, msg["bytes"])
                        pcm = await asyncio.to_thread(decoder.drain_pcm)
                    except Exception as e:
                        logger.exception("webm decode write failed: %s", e)
                        await websocket.send_json(
                            {"type": "error", "stage": "decode", "detail": str(e)[:500]}
                        )
                        continue
                    session_pcm.extend(pcm)
                    pieces = audio_buf.feed(pcm)
                else:
                    session_raw.extend(msg["bytes"])
                    pieces = audio_buf.feed(msg["bytes"])

                for piece in pieces:
                    if not piece:
                        continue
                    try:
                        text = (
                            await _transcribe_pcm_chunk(piece, lang_hint, vad_prefs)
                            if decoder is not None
                            else await _transcribe_container_chunk(piece, lang_hint, vad_prefs)
                        )
                    except Exception as e:
                        logger.exception("transcribe_chunk failed: %s", e)
                        await websocket.send_json(
                            {"type": "error", "stage": "asr", "detail": str(e)[:500]}
                        )
                        continue
                    stream_end = len(session_pcm) if decoder is not None else len(session_raw)
                    start_s, end_s = _piece_time_bounds(
                        piece_len=len(piece),
                        stream_end_byte=stream_end,
                        bytes_per_second=bps,
                    )
                    _append_partial_entry(
                        partial_entries, text=text, start=start_s, end=end_s
                    )
                    await hub.publish(
                        cid_str,
                        {
                            "type": "transcript_partial",
                            "conversation_id": cid_str,
                            "text": text,
                            "start": start_s,
                            "end": end_s,
                            "realtime_mode": mode,
                            "pcm": use_pcm,
                            "processing_tier": "fast",
                        },
                    )
                    await websocket.send_json(
                        {
                            "type": "asr_ok",
                            "bytes_ingested": len(piece),
                            "text_len": len(text),
                            "pcm": use_pcm,
                        }
                    )

                last_fast_persist_at, fast_snapshot_seq = await _maybe_persist_fast_snapshot(
                    user_id=str(user.id),
                    conversation_id=cid_str,
                    partial_entries=partial_entries,
                    pcm_len=len(session_pcm),
                    lim=lim,
                    last_persist_at=last_fast_persist_at,
                    fast_snapshot_seq=fast_snapshot_seq,
                    hub=hub,
                    cid_str=cid_str,
                    step_s=step_s,
                    overlap_s=overlap_s,
                )

                if not handoff_sent and lim.autoprolong_enabled:
                    hit, ap_reason = _autoprolong_limits_hit(
                        len(session_pcm), len(session_raw), use_pcm
                    )
                    if hit:
                        handoff_sent = True
                        can_rotate = (
                            len(session_pcm) >= MIN_REALTIME_FINALIZE_PCM_BYTES
                            or len(session_raw) >= MIN_AUDIO_CONTENT_BYTES
                        )
                        if not can_rotate:
                            await websocket.send_json(
                                {
                                    "type": "autoprolong_error",
                                    "conversation_id": cid_str,
                                    "detail": "insufficient_audio_for_rotate",
                                    "reason": ap_reason,
                                }
                            )
                            handoff_sent = False
                            continue
                        fid = f"autoprolong-{uuid4()}"
                        ok_fin, err_fin = await asyncio.to_thread(
                            finalize_realtime_session,
                            user_id=str(user.id),
                            conversation_id=cid_str,
                            language=lang_hint,
                            pcm_mono_s16le=bytes(session_pcm),
                            raw_container_bytes=bytes(session_raw),
                            partial_texts=list(partial_entries),
                            finalize_id=fid,
                            prefer_pcm=use_pcm,
                            step_s=step_s,
                            overlap_s=overlap_s,
                        )
                        if not ok_fin:
                            await websocket.send_json(
                                {
                                    "type": "autoprolong_error",
                                    "conversation_id": cid_str,
                                    "detail": err_fin,
                                    "reason": ap_reason,
                                }
                            )
                            handoff_sent = False
                            continue
                        meta = await asyncio.to_thread(
                            _create_autoprolong_continuation_sync,
                            conversation_id,
                            user.id,
                        )
                        if meta is None:
                            await websocket.send_json(
                                {
                                    "type": "autoprolong_error",
                                    "conversation_id": cid_str,
                                    "detail": "branch_failed",
                                    "reason": ap_reason,
                                }
                            )
                            continue
                        await websocket.send_json(
                            {
                                "type": "autoprolong_handoff",
                                "conversation_id": cid_str,
                                "finalize_id": fid,
                                "reason": ap_reason,
                                **meta,
                            }
                        )
                        await websocket.close(code=1000)
                        return

            elif "text" in msg:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    data = {"raw": msg["text"][:200]}
                    await websocket.send_json({"type": "ack_text", "echo": data})
                    continue
                if isinstance(data, dict) and data.get("type") == "finalize":
                    fid_raw = data.get("finalize_id")
                    finalize_id = (
                        str(fid_raw).strip()
                        if fid_raw is not None and str(fid_raw).strip()
                        else ""
                    )
                    if not finalize_id:
                        await websocket.send_json(
                            {
                                "type": "finalize_error",
                                "conversation_id": cid_str,
                                "detail": "finalize_id is required",
                            }
                        )
                        continue
                    can_finalize = (
                        len(session_pcm) >= MIN_REALTIME_FINALIZE_PCM_BYTES
                        or len(session_raw) >= MIN_AUDIO_CONTENT_BYTES
                    )
                    if not can_finalize:
                        await websocket.send_json(
                            {
                                "type": "finalize_error",
                                "conversation_id": cid_str,
                                "detail": "insufficient_audio",
                            }
                        )
                        continue
                    claim = await asyncio.to_thread(
                        try_claim_finalize_pending,
                        cid_str,
                        finalize_id,
                    )
                    if claim == "duplicate":
                        await websocket.send_json(
                            {
                                "type": "finalize_ack",
                                "conversation_id": cid_str,
                                "finalize_id": finalize_id,
                                "status": "duplicate",
                            }
                        )
                        continue
                    if not decoder_tail_flushed:
                        await _flush_tail_asr(
                            decoder=decoder,
                            audio_buf=audio_buf,
                            session_pcm=session_pcm,
                            session_raw=session_raw,
                            use_pcm=use_pcm,
                            mode=mode,
                            partial_entries=partial_entries,
                            hub=hub,
                            cid_str=cid_str,
                            lang_hint=lang_hint,
                            vad_prefs=vad_prefs,
                            bps=bps,
                            close_decoder=True,
                            final=True,
                        )
                        decoder_tail_flushed = True
                        decoder = None
                    ok, err = await asyncio.to_thread(
                        lambda: finalize_realtime_session(
                            user_id=str(user.id),
                            conversation_id=cid_str,
                            language=lang_hint,
                            pcm_mono_s16le=bytes(session_pcm),
                            raw_container_bytes=bytes(session_raw),
                            partial_texts=list(partial_entries),
                            finalize_id=finalize_id,
                            prefer_pcm=use_pcm,
                            step_s=step_s,
                            overlap_s=overlap_s,
                        )
                    )
                    if not ok:
                        # Allow client retry with the same finalize_id after transient errors.
                        await asyncio.to_thread(release_finalize_pending, cid_str, finalize_id)
                        await websocket.send_json(
                            {
                                "type": "finalize_error",
                                "conversation_id": cid_str,
                                "detail": err,
                            }
                        )
                        continue
                    await asyncio.to_thread(mark_finalize_done, cid_str, finalize_id)
                    await websocket.send_json(
                        {
                            "type": "finalize_ack",
                            "conversation_id": cid_str,
                            "finalize_id": finalize_id,
                            "status": "accepted",
                        }
                    )
                    continue
                await websocket.send_json({"type": "ack_text", "echo": data})
    except Exception as e:
        logger.exception("WS audio error: %s", e)
    finally:
        if not decoder_tail_flushed:
            try:
                await _flush_tail_asr(
                    decoder=decoder,
                    audio_buf=audio_buf,
                    session_pcm=session_pcm,
                    session_raw=session_raw,
                    use_pcm=use_pcm,
                    mode=mode,
                    partial_entries=partial_entries,
                    hub=hub,
                    cid_str=cid_str,
                    lang_hint=lang_hint,
                    vad_prefs=vad_prefs,
                    bps=bps,
                    close_decoder=True,
                    final=True,
                )
            except Exception as e:
                logger.exception("WS audio tail flush failed: %s", e)


@router.websocket("/transcript/{conversation_id}")
async def websocket_transcript(
    websocket: WebSocket,
    conversation_id: UUID,
    db: Annotated[Session, Depends(get_db)],
):
    """Подписка на частичные транскрипты (memory или Redis hub)."""
    token, subproto, ws_reject = extract_access_token_for_websocket(websocket)
    if ws_reject:
        await websocket.close(code=_WS_CLOSE_POLICY, reason=ws_reject)
        return

    user = _user_from_token(db, token or "")
    if user is None:
        await websocket.close(code=_WS_CLOSE_POLICY, reason="invalid_token")
        return

    conv = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )
    if conv is None:
        await websocket.close(code=_WS_CLOSE_POLICY, reason="forbidden_or_missing")
        return

    hub = get_transcript_hub()
    cid_str = str(conversation_id)
    queue = await hub.subscribe(cid_str)

    await websocket.accept(subprotocol=subproto)
    await websocket.send_json(
        {
            "type": "ready",
            "channel": "transcript",
            "conversation_id": cid_str,
            "message": "Subscribed to partial transcripts for this conversation.",
        }
    )

    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=60.0)
                await websocket.send_json(payload)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "keepalive"})
    except WebSocketDisconnect:
        logger.info("WS transcript disconnected conversation_id=%s", conversation_id)
    except Exception as e:
        logger.exception("WS transcript error: %s", e)
    finally:
        await hub.unsubscribe(cid_str, queue)
