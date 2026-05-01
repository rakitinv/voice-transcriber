"""
WebSocket: realtime audio и transcript (префикс приложения /ws, не /api).

Контракт: docs/WEBSOCKET.md
"""

from __future__ import annotations

import asyncio
import json
import os
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
from .realtime_finalize import MIN_REALTIME_FINALIZE_PCM_BYTES, finalize_realtime_session
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
        pcm_sample_rate=pcm_sample_rate,
    )
    return RealtimeAudioBuffer(params)


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
    partial_texts: list[str] = []
    handoff_sent = False

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
                    if text.strip():
                        partial_texts.append(text.strip())
                    await hub.publish(
                        cid_str,
                        {
                            "type": "transcript_partial",
                            "conversation_id": cid_str,
                            "text": text,
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
                            partial_texts=list(partial_texts),
                            finalize_id=fid,
                            prefer_pcm=use_pcm,
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
                    ok, err = await asyncio.to_thread(
                        lambda: finalize_realtime_session(
                            user_id=str(user.id),
                            conversation_id=cid_str,
                            language=lang_hint,
                            pcm_mono_s16le=bytes(session_pcm),
                            raw_container_bytes=bytes(session_raw),
                            partial_texts=list(partial_texts),
                            finalize_id=finalize_id,
                            prefer_pcm=use_pcm,
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
        # Best-effort: flush remaining decoder/buffer so short recordings still produce at least one partial.
        try:
            if decoder is not None:
                # Important: close stdin and wait for ffmpeg to flush remaining PCM,
                # then drain any bytes produced by the reader thread.
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
                else:
                    pieces = []
            else:
                pieces = []

            # If windowed mode never reached step threshold, force a final pass with whatever is buffered.
            # This avoids "no realtime text" on short clips when chunk_ms is large.
            if not pieces and mode == "windowed":
                tail = getattr(audio_buf, "_buf", None)  # type: ignore[attr-defined]
                if isinstance(tail, (bytearray, bytes)) and len(tail) > 0:
                    pieces = [bytes(tail)]

            for piece in pieces:
                if not piece:
                    continue
                try:
                    text = await (
                        _transcribe_pcm_chunk(piece, lang_hint, vad_prefs)
                        if use_pcm
                        else _transcribe_container_chunk(piece, lang_hint, vad_prefs)
                    )
                except Exception:
                    continue
                if text.strip():
                    partial_texts.append(text.strip())
                    await hub.publish(
                        cid_str,
                        {
                            "type": "transcript_partial",
                            "conversation_id": cid_str,
                            "text": text,
                            "realtime_mode": mode,
                            "pcm": use_pcm,
                            "final": True,
                            "processing_tier": "fast",
                        },
                    )
        finally:
            # decoder already closed above
            pass


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
