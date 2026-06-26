"""Unit tests for pipeline failure classification (§9-safe hints)."""

from __future__ import annotations

from uuid import uuid4

from app.services.pipeline_error_classify import classify_pipeline_failure, pipeline_failure_detail
from app.services.pipeline_event_write import record_pipeline_event


def test_diarize_output_itertracks_classified() -> None:
    exc = AttributeError("'DiarizeOutput' object has no attribute 'itertracks'")
    out = classify_pipeline_failure(exc, stage="diarization")
    assert out["reason_code"] == "pyannote_api_mismatch"
    assert "itertracks" in out["error_hint"]
    assert out["exception_type"] == "AttributeError"


def test_ollama_model_not_found_summary() -> None:
    msg = (
        "Ollama returned 404 for http://host.docker.internal:11434/api/generate. "
        "Ollama says: model 'ilyagusev/saiga_llama3:latest' not found"
    )
    out = classify_pipeline_failure(msg, stage="summary")
    assert out["reason_code"] == "llm_model_not_found"
    assert "404" in out["error_hint"]


def test_cuda_oom_any_stage() -> None:
    out = classify_pipeline_failure(RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB"))
    assert out["reason_code"] == "cuda_oom"


def test_hf_token_redacted_in_hint() -> None:
    # Synthetic token (not a real HF credential) — must not appear verbatim in hints.
    fake_token = "hf_" + "x" * 34
    msg = f"Download failed: {fake_token} is invalid"
    out = classify_pipeline_failure(msg, stage="diarization")
    assert fake_token not in out["error_hint"]
    assert "hf_***" in out["error_hint"]


def test_pipeline_failure_detail_override_reason_code() -> None:
    out = pipeline_failure_detail(
        "chunk 3 failed: timeout",
        stage="asr",
        reason_code="parallel_chunk_errors",
    )
    assert out["reason_code"] == "parallel_chunk_errors"
    assert "timeout" in out["error_hint"]


def test_record_pipeline_event_preserves_error_hint() -> None:
    class _Db:
        added = None

        def add(self, row) -> None:
            self.added = row

    db = _Db()
    record_pipeline_event(
        db,
        conversation_id=uuid4(),
        event_type="diarization_failed",
        detail={
            "reason_code": "pyannote_api_mismatch",
            "error_hint": "'DiarizeOutput' object has no attribute 'itertracks'",
            "exception_type": "AttributeError",
        },
    )
    assert db.added.detail["error_hint"].startswith("'DiarizeOutput'")
    assert db.added.detail["exception_type"] == "AttributeError"
