"""Pipeline events for recording-session LLM summary."""

from __future__ import annotations

from uuid import uuid4

from app.services.pipeline_event_write import record_pipeline_event
from app.services.pipeline_error_classify import classify_pipeline_failure


def test_summary_failure_reason_code_ollama_404() -> None:
    msg = (
        "Ollama returned 404 for http://host.docker.internal:11434/api/generate. "
        "Ollama says: model 'ilyagusev/saiga_llama3:latest' not found"
    )
    assert classify_pipeline_failure(msg, stage="summary")["reason_code"] == "llm_model_not_found"


def test_summary_failure_reason_code_unreachable() -> None:
    assert (
        classify_pipeline_failure("Cannot reach Ollama at http://x/api/generate", stage="summary")[
            "reason_code"
        ]
        == "llm_unreachable"
    )


def test_record_summary_started_event_type_allowed() -> None:
    """record_pipeline_event must accept summary_* (not silently drop)."""

    class _Db:
        added = None

        def add(self, row) -> None:
            self.added = row

    db = _Db()
    cid = uuid4()
    record_pipeline_event(db, conversation_id=cid, event_type="summary_started")
    assert db.added is not None
    assert db.added.event_type == "summary_started"
    assert db.added.conversation_id == cid


def test_record_summary_failed_with_reason_code() -> None:
    class _Db:
        added = None

        def add(self, row) -> None:
            self.added = row

    db = _Db()
    record_pipeline_event(
        db,
        conversation_id=uuid4(),
        event_type="summary_failed",
        detail={
            "reason_code": "llm_model_not_found",
            "error_hint": "model 'foo' not found",
        },
    )
    assert db.added.detail["reason_code"] == "llm_model_not_found"
    assert "foo" in db.added.detail["error_hint"]
