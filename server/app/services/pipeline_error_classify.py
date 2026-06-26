"""Classify worker failures for pipeline_events.detail (§9 — no transcript text)."""

from __future__ import annotations

import re
from typing import Any

_MAX_HINT = 500
_MAX_REASON = 128
_MAX_EXC_TYPE = 64

_SECRET_PATTERNS = (
    (re.compile(r"\bhf_[a-zA-Z0-9]{8,}\b"), "hf_***"),
    (re.compile(r"(?i)\bbearer\s+\S+"), "bearer ***"),
    (re.compile(r"(?i)(api[_-]?key|token|password)\s*[=:]\s*\S+"), r"\1=***"),
)


def _sanitize_error_hint(msg: str) -> str:
    s = " ".join((msg or "").strip().split())
    for pattern, repl in _SECRET_PATTERNS:
        s = pattern.sub(repl, s)
    if len(s) > _MAX_HINT:
        return s[: _MAX_HINT - 1] + "…"
    return s


def _reason_code(name: str) -> str:
    s = (name or "exception").strip().lower().replace(" ", "_")
    return s[:_MAX_REASON] if s else "exception"


def classify_pipeline_failure(
    exc: BaseException | str,
    *,
    stage: str = "asr",
) -> dict[str, Any]:
    """
    Map an exception to pipeline_events.detail fields:
    reason_code, error_hint, and optional exception_type.
    """
    if isinstance(exc, BaseException):
        msg = str(exc).strip() or repr(exc)
        exc_type = type(exc).__name__
    else:
        msg = str(exc).strip()
        exc_type = ""

    lower = msg.lower()
    stage = (stage or "asr").strip().lower()
    reason = "exception"

    if "cuda out of memory" in lower or "cudamalloc" in lower:
        reason = "cuda_oom"
    elif "no cuda" in lower or "cuda is not available" in lower or "cuda unavailable" in lower:
        reason = "cuda_unavailable"
    elif "timed out" in lower or "timeout" in lower:
        reason = "timeout"
    elif "ffmpeg" in lower and ("not found" in lower or "no such file" in lower):
        reason = "ffmpeg_error"
    elif any(x in lower for x in ("nosuchkey", "s3", "minio", "bucket")) and any(
        x in lower for x in ("404", "not found", "access denied", "forbidden", "error")
    ):
        reason = "s3_error"

    if "model checksum failed" in lower or "checksum failed" in lower:
        reason = "model_checksum_failed"
    elif stage == "asr" and "parallel" in lower and "chunk" in lower:
        reason = "parallel_chunk_errors"
    elif stage == "diarization":
        if "no diarization provider" in lower:
            reason = "no_diarization_provider"
        elif "audio too small" in lower:
            reason = "audio_too_small"
        elif "itertracks" in lower or "diarizeoutput" in lower:
            reason = "pyannote_api_mismatch"
        elif any(x in lower for x in ("403", "gated", "authorized", "accept the user conditions")):
            reason = "hf_gated"
        elif "401" in lower and ("hugging" in lower or "hf" in lower or "token" in lower):
            reason = "hf_auth"
        elif reason == "exception":
            reason = "diarization_error"
    elif stage == "summary":
        if msg == "no_final_segments":
            reason = "no_final_segments"
        elif "returned 404" in lower or ("model" in lower and "not found" in lower):
            reason = "llm_model_not_found"
        elif "cannot reach ollama" in lower:
            reason = "llm_unreachable"
        elif "ollama_empty_response" in lower:
            reason = "llm_empty_response"
        elif reason == "exception":
            reason = "llm_error"
    elif stage == "asr":
        if "gigaam" in lower and ("gpu" in lower or "cuda" in lower):
            reason = "asr_provider_error"
        elif reason == "exception":
            reason = "asr_error"

    out: dict[str, Any] = {
        "reason_code": _reason_code(reason),
        "error_hint": _sanitize_error_hint(msg),
    }
    if exc_type:
        out["exception_type"] = exc_type[:_MAX_EXC_TYPE]
    return out


def pipeline_failure_detail(
    exc: BaseException | str,
    *,
    stage: str = "asr",
    reason_code: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a detail dict for *_failed pipeline events."""
    base = classify_pipeline_failure(exc, stage=stage)
    if reason_code:
        base["reason_code"] = _reason_code(reason_code)
    if extra:
        for k, v in extra.items():
            if k not in base and v is not None:
                base[k] = v
    return base
