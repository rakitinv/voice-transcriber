"""Recording-session summary milestones for pipeline_events (§9-safe)."""

from __future__ import annotations

from typing import Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.pipeline_error_classify import pipeline_failure_detail
from app.services.pipeline_event_write import record_pipeline_event


def record_summary_pipeline_events(
    db: Session,
    conversation_ids: Iterable[UUID],
    event_type: str,
    *,
    reason_code: str | None = None,
    error_hint: str | None = None,
    exc: BaseException | str | None = None,
) -> None:
    detail: dict | None = None
    if exc is not None:
        detail = pipeline_failure_detail(exc, stage="summary", reason_code=reason_code)
    elif reason_code or error_hint:
        detail = {}
        if reason_code:
            detail["reason_code"] = reason_code
        if error_hint:
            detail["error_hint"] = error_hint
    for cid in conversation_ids:
        record_pipeline_event(
            db,
            conversation_id=cid,
            event_type=event_type,
            detail=detail,
        )
