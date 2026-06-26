"""
Versioned admin routes (sprint 1–4: infra, conversations, tools, actions, audit, pipeline snapshot).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

import httpx
import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from admin_api.celery_monitor import get_queue_consumer_status_cached
from admin_api.audit import record_admin_audit_event
from admin_api.audit_dedupe import should_emit_admin_read_audit
from admin_api.pipeline_events_read import (
    count_pipeline_events,
    list_pipeline_events,
    list_pipeline_events_newer_than,
)
from admin_api.pipeline_settings import build_pipeline_runtime_snapshot, snapshot_to_jsonable
from admin_api.audit_read import count_admin_audit_events, list_admin_audit_events
from admin_api.conversations_read import (
    count_admin_conversations,
    get_conversation_for_admin,
    get_recording_session_summary_row,
    list_admin_conversations,
    list_embeddings_for_conversation,
    list_transcripts_for_conversation,
)
from admin_api.dependencies import AdminPrincipal, require_admin_principal
from admin_api.meta_sanitize import sanitize_transcript_meta
from admin_api.pipeline_actions import (
    admin_enqueue_embedding_reindex,
    admin_enqueue_rediarize,
    admin_enqueue_resummary,
    admin_enqueue_retranscribe,
)
from core.config import app_config
from core.db import get_db
from core.deployment_compat import QueueConsumerSlice, collect_compatibility_issues, deploy_profile
from core.logging import logger

router = APIRouter(prefix="/admin/api/v1", tags=["admin-v1"])


def _record_deduped_admin_read_audit(
    principal: AdminPrincipal, *, action: str, detail: str | None = None
) -> None:
    uid = str(principal.user.id)
    d = (detail or "").strip()
    if not should_emit_admin_read_audit(admin_user_id=uid, action=action, detail_fingerprint=d):
        return
    try:
        record_admin_audit_event(
            admin_user_id=principal.user.id,
            action=action,
            detail=d or None,
        )
    except Exception:
        logger.warning("admin audit persist failed (%s)", action, exc_info=True)


def _truncate_admin_pipeline_text(value: str | None, max_len: int = 280) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


class ListConversationsQueryParams(BaseModel):
    """GET /conversations query string: unknown parameters are rejected (see ``parse_list_conversations_query``)."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    user_id: UUID | None = Field(default=None, description="Filter by conversation owner")
    transcript_status: str | None = Field(
        default=None,
        description="Filter by active transcript status (pending|running|success|failed)",
    )
    transcript_kind: str | None = Field(
        default=None, description="Filter by active transcript kind (exact match)"
    )
    session_summary_status: str | None = Field(
        default=None,
        description="Filter by recording_session_summaries.status for this chain",
    )
    session_summary_missing: bool | None = Field(
        default=None,
        description="If true, only rows with no recording_session_summaries row; if false, only with a row",
    )
    has_audio: bool | None = Field(
        default=None,
        description="If true, audio_uploaded_at is set; if false, not uploaded",
    )
    recording_session_id: UUID | None = Field(
        default=None,
        description="Filter by recording_session_id (autoprolong chain)",
    )


def parse_list_conversations_query(request: Request) -> ListConversationsQueryParams:
    """
    FastAPI only forwards declared query keys into Pydantic models; unknown keys are dropped
    silently, so we reject extras explicitly (ADMIN_OPS_SPRINT5_CHECKLIST O2).
    """
    qp = request.query_params
    allowed = frozenset(ListConversationsQueryParams.model_fields.keys())
    incoming = frozenset(qp.keys())
    extra = incoming - allowed
    if extra:
        first = sorted(extra)[0]
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "type": "extra_forbidden",
                    "loc": ("query", first),
                    "msg": "Extra inputs are not permitted",
                }
            ],
        )
    payload: dict[str, object] = {}
    for name in allowed:
        if name not in incoming:
            continue
        raw = qp.get(name)
        if raw is None or raw == "":
            continue
        if name in ("session_summary_missing", "has_audio"):
            low = raw.strip().lower()
            if low in ("true", "1", "yes"):
                payload[name] = True
            elif low in ("false", "0", "no"):
                payload[name] = False
            else:
                payload[name] = raw
        else:
            payload[name] = raw
    return ListConversationsQueryParams.model_validate(payload)


class ListPipelineEventsQueryParams(BaseModel):
    """GET /pipeline-events — unknown query keys rejected."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    conversation_id: UUID | None = None
    event_type: str | None = Field(
        default=None,
        description="Exact pipeline_events.event_type (e.g. asr_started, summary_failed)",
    )


def parse_list_pipeline_events_query(request: Request) -> ListPipelineEventsQueryParams:
    qp = request.query_params
    allowed = frozenset(ListPipelineEventsQueryParams.model_fields.keys())
    incoming = frozenset(qp.keys())
    extra = incoming - allowed
    if extra:
        first = sorted(extra)[0]
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "type": "extra_forbidden",
                    "loc": ("query", first),
                    "msg": "Extra inputs are not permitted",
                }
            ],
        )
    payload: dict[str, object] = {}
    for name in allowed:
        if name not in incoming:
            continue
        raw = qp.get(name)
        if raw is None or raw == "":
            continue
        payload[name] = raw
    return ListPipelineEventsQueryParams.model_validate(payload)


class PipelineEventsWaitQueryParams(BaseModel):
    """GET /pipeline-events/wait — long poll; unknown query keys rejected."""

    model_config = ConfigDict(extra="forbid")

    since_created_at: datetime
    since_id: UUID
    conversation_id: UUID | None = None
    event_type: str | None = Field(
        default=None,
        description="Exact pipeline_events.event_type filter",
    )
    timeout_seconds: int = Field(default=25, ge=1, le=55)


def parse_pipeline_events_wait_query(request: Request) -> PipelineEventsWaitQueryParams:
    qp = request.query_params
    allowed = frozenset(PipelineEventsWaitQueryParams.model_fields.keys())
    incoming = frozenset(qp.keys())
    extra = incoming - allowed
    if extra:
        first = sorted(extra)[0]
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "type": "extra_forbidden",
                    "loc": ("query", first),
                    "msg": "Extra inputs are not permitted",
                }
            ],
        )
    payload: dict[str, object] = {}
    for name in allowed:
        if name not in incoming:
            continue
        raw = qp.get(name)
        if raw is None or raw == "":
            continue
        payload[name] = raw
    return PipelineEventsWaitQueryParams.model_validate(payload)


class AdminMeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: str
    roles: list[str] = Field(default_factory=list)


class AdminLiveTickResponse(BaseModel):
    """Lightweight clock tick for live refresh hints — no conversation payloads (§9)."""

    model_config = ConfigDict(extra="forbid")

    tick_ms: int = Field(..., description="UTC Unix time in milliseconds")
    schema_version: int = Field(default=1, description="Increment when this contract changes")


class InfraCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    detail: str | None = None


class QueueConsumerCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue: str
    consumer_responding: bool
    queue_depth: int | None = None
    detail: str | None = None


class CompatibilityIssueOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["error", "warning"]
    message: str
    hint: str | None = None


class InfrastructureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    postgres: InfraCheck
    redis: InfraCheck
    main_api: InfraCheck
    celery_queues: list[QueueConsumerCheck] = Field(default_factory=list)
    deploy_profile: str = Field(
        ...,
        description="VT_DEPLOY_PROFILE: cpu (default stack) or gpu",
    )
    compatibility_issues: list[CompatibilityIssueOut] = Field(default_factory=list)


class ExternalToolItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str


class ExternalToolsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[ExternalToolItem] = Field(default_factory=list)


class AdminConversationListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    audio_uploaded_at: datetime | None
    audio_object_ext: str
    recording_session_id: str
    active_transcript_id: int | None
    active_transcript_revision: int | None
    active_transcript_kind: str | None
    active_transcript_status: str | None
    transcript_revision_count: int = Field(
        ...,
        description="Number of transcript rows for this conversation (from DB, no S3)",
    )
    session_summary_status: str | None = None
    session_summary_error: str | None = Field(
        default=None,
        description="Truncated pipeline error for the chain summary (§9 — no transcript text)",
    )
    asr_chunk_completed: int | None = Field(
        default=None,
        description="Busy ASR job slice progress (pending/running asr row), if any",
    )
    asr_chunk_total: int | None = Field(
        default=None,
        description="Total ASR time slices for the busy ASR job, if chunking is active",
    )


class AdminConversationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminConversationListItem]
    total: int
    limit: int
    offset: int


class AdminTranscriptRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    revision: int
    kind: str
    status: str
    created_at: datetime
    updated_at: datetime
    meta: dict | None = None
    asr_chunk_completed: int | None = None
    asr_chunk_total: int | None = None


class AdminRecordingSessionSummarySlice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording_session_id: str
    status: str
    error: str | None = None
    meta: dict | None = None
    created_at: datetime
    updated_at: datetime


class AdminEmbeddingSlice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    transcript_id: int
    kind: str
    created_at: datetime
    vector_dimension: int


class AdminConversationDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    audio_uploaded_at: datetime | None
    audio_object_ext: str
    recording_session_id: str
    previous_conversation_id: str | None
    client_realtime_mode: str | None
    client_chunk_ms: int | None
    active_transcript_id: int | None
    product_conversation_url: str | None = None
    transcripts: list[AdminTranscriptRevision]
    recording_session_summary: AdminRecordingSessionSummarySlice | None = None
    embeddings: list[AdminEmbeddingSlice]


class AdminAuditEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    admin_user_id: str
    action: str
    conversation_id: str | None = None
    detail: str | None = None
    created_at: datetime


class AdminAuditEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminAuditEventItem]
    total: int
    limit: int
    offset: int


class AdminPipelineEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    conversation_id: str
    event_type: str
    transcript_id: int | None = None
    detail: dict | None = None
    created_at: datetime


class AdminPipelineEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminPipelineEventItem]
    total: int
    limit: int
    offset: int


class AdminPipelineEventsWaitResponse(BaseModel):
    """Long-poll: new rows after cursor, or empty with timed_out."""

    model_config = ConfigDict(extra="forbid")

    items: list[AdminPipelineEventItem]
    timed_out: bool


class PipelineAsrProviderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool
    model: str | None = None
    impl: str | None = None


class PipelineAsrBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_provider: str
    realtime_provider: str | None = None
    final_provider: str | None = None
    recognition_model: str | None = None
    realtime_recognition_model: str | None = None
    final_recognition_model: str | None = None
    providers: list[PipelineAsrProviderItem] = Field(default_factory=list)


class PipelineDiarizationProviderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool
    impl: str | None = None
    model: str | None = None
    device: str | None = None
    hf_token_env: str | None = None
    offline_models: bool = False


class PipelineDiarizationBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    default_provider: str | None = None
    turn_level_retranscription: bool = False
    providers: list[PipelineDiarizationProviderItem] = Field(default_factory=list)


class PipelineLlmProviderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool
    base_url: str | None = None
    model: str | None = None


class PipelineLlmBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_provider: str
    session_summary_enabled: bool = False
    session_summary_max_input_chars: int = 120_000
    providers: list[PipelineLlmProviderItem] = Field(default_factory=list)


class PipelineEmbeddingsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    provider: str
    model: str
    base_url: str | None = None
    openai_base_url: str | None = None
    timeout_seconds: float
    max_input_chars: int


class PipelineLimitsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_ms_min: int
    chunk_ms_max: int
    default_realtime_mode: str
    allowed_realtime_modes: list[str] = Field(default_factory=list)
    max_window_ms: int
    autoprolong_enabled: bool = False
    autoprolong_tail_seconds: float = 0.0


class PipelineSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: str
    asr: PipelineAsrBlock
    diarization: PipelineDiarizationBlock
    llm: PipelineLlmBlock
    embeddings: PipelineEmbeddingsBlock
    limits: PipelineLimitsBlock


def _main_api_base_url() -> str:
    return (os.environ.get("VT_PUBLIC_API_URL") or "http://localhost:8002").strip().rstrip("/")


@router.get("/me", response_model=AdminMeResponse)
async def admin_me(principal: Annotated[AdminPrincipal, Depends(require_admin_principal)]):
    roles = principal.membership.roles
    if not isinstance(roles, list):
        roles = []
    role_strs = [str(x) for x in roles]
    try:
        record_admin_audit_event(
            admin_user_id=principal.user.id,
            action="admin_console_session",
            detail="endpoint=/admin/api/v1/me",
        )
    except Exception:
        logger.warning("admin audit persist failed (admin_console_session)", exc_info=True)
    return AdminMeResponse(
        user_id=str(principal.user.id),
        email=principal.user.email,
        roles=role_strs,
    )


@router.get("/live-tick", response_model=AdminLiveTickResponse)
async def admin_live_tick(principal: Annotated[AdminPrincipal, Depends(require_admin_principal)]):
    """
    Sprint 7: optional refresh signal without streaming — payload must never include §9 fields.
    """
    logger.debug("admin live_tick user_id=%s", principal.user.id)
    tick = int(datetime.now(timezone.utc).timestamp() * 1000)
    return AdminLiveTickResponse(tick_ms=tick, schema_version=1)


@router.get("/pipeline-settings", response_model=PipelineSettingsResponse)
async def pipeline_settings(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
):
    _record_deduped_admin_read_audit(principal, action="pipeline_settings_view")
    snap = build_pipeline_runtime_snapshot()
    return PipelineSettingsResponse.model_validate(snapshot_to_jsonable(snap))


@router.get("/external-tools", response_model=ExternalToolsResponse)
async def external_tools(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
):
    _record_deduped_admin_read_audit(principal, action="external_tools_view")
    tools = [
        ExternalToolItem(name=t.name, url=t.url) for t in app_config.admin_console.external_tools
    ]
    return ExternalToolsResponse(tools=tools)


@router.get("/infrastructure", response_model=InfrastructureResponse)
async def infrastructure_status(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
    db: Annotated[Session, Depends(get_db)],
):
    _record_deduped_admin_read_audit(principal, action="infrastructure_view")
    pg = InfraCheck(ok=False, detail=None)
    try:
        db.execute(text("SELECT 1"))
        pg = InfraCheck(ok=True, detail=None)
    except Exception as e:
        pg = InfraCheck(ok=False, detail=str(e)[:500])

    rd = InfraCheck(ok=False, detail=None)
    try:
        r = redis.Redis.from_url(app_config.redis.url, socket_connect_timeout=2.0)
        try:
            if r.ping():
                rd = InfraCheck(ok=True, detail=None)
            else:
                rd = InfraCheck(ok=False, detail="PING returned false")
        finally:
            r.close()
    except Exception as e:
        rd = InfraCheck(ok=False, detail=str(e)[:500])

    api = InfraCheck(ok=False, detail=None)
    base = _main_api_base_url()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base}/health")
            if resp.status_code == 200:
                api = InfraCheck(ok=True, detail=f"HTTP {resp.status_code}")
            else:
                api = InfraCheck(ok=False, detail=f"HTTP {resp.status_code}")
    except Exception as e:
        api = InfraCheck(ok=False, detail=str(e)[:500])

    qrows = get_queue_consumer_status_cached()
    celery_queues = [
        QueueConsumerCheck(
            queue=q.queue,
            consumer_responding=q.consumer_responding,
            queue_depth=q.queue_depth,
            detail=q.detail,
        )
        for q in qrows
    ]
    queue_slices = [
        QueueConsumerSlice(queue=q.queue, consumer_responding=q.consumer_responding) for q in qrows
    ]
    compat = collect_compatibility_issues(celery_queues=queue_slices)
    compatibility_issues = [
        CompatibilityIssueOut(
            code=i.code,
            severity=i.severity,
            message=i.message,
            hint=i.hint,
        )
        for i in compat
    ]

    return InfrastructureResponse(
        postgres=pg,
        redis=rd,
        main_api=api,
        celery_queues=celery_queues,
        deploy_profile=deploy_profile(),
        compatibility_issues=compatibility_issues,
    )


@router.get("/audit-events", response_model=AdminAuditEventsResponse)
async def list_audit_events(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: Annotated[str | None, Query(description="Exact action name filter")] = None,
    conversation_id: Annotated[UUID | None, Query()] = None,
    admin_user_id: Annotated[UUID | None, Query()] = None,
):
    fp = json.dumps(
        {
            "limit": limit,
            "offset": offset,
            "action": action,
            "conversation_id": str(conversation_id) if conversation_id else None,
            "admin_user_id": str(admin_user_id) if admin_user_id else None,
        },
        sort_keys=True,
    )
    _record_deduped_admin_read_audit(principal, action="audit_events_list_view", detail=fp)
    act = action.strip() if isinstance(action, str) and action.strip() else None
    total = count_admin_audit_events(
        db,
        action=act,
        conversation_id=conversation_id,
        admin_user_id=admin_user_id,
    )
    rows = list_admin_audit_events(
        db,
        action=act,
        conversation_id=conversation_id,
        admin_user_id=admin_user_id,
        limit=limit,
        offset=offset,
    )
    items = [
        AdminAuditEventItem(
            id=str(r.id),
            admin_user_id=str(r.admin_user_id),
            action=r.action,
            conversation_id=str(r.conversation_id) if r.conversation_id else None,
            detail=r.detail,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return AdminAuditEventsResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/pipeline-events", response_model=AdminPipelineEventsResponse)
async def list_pipeline_events_endpoint(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
    q: Annotated[ListPipelineEventsQueryParams, Depends(parse_list_pipeline_events_query)],
    db: Annotated[Session, Depends(get_db)],
):
    fp = json.dumps(
        {
            "limit": q.limit,
            "offset": q.offset,
            "conversation_id": str(q.conversation_id) if q.conversation_id else None,
            "event_type": q.event_type,
        },
        sort_keys=True,
    )
    _record_deduped_admin_read_audit(principal, action="pipeline_events_list_view", detail=fp)
    et = q.event_type.strip() if isinstance(q.event_type, str) and q.event_type.strip() else None
    total = count_pipeline_events(
        db, conversation_id=q.conversation_id, event_type=et
    )
    rows = list_pipeline_events(
        db,
        conversation_id=q.conversation_id,
        event_type=et,
        limit=q.limit,
        offset=q.offset,
    )
    items = _pipeline_event_rows_to_items(rows)
    return AdminPipelineEventsResponse(items=items, total=total, limit=q.limit, offset=q.offset)


def _pipeline_event_rows_to_items(rows: list) -> list[AdminPipelineEventItem]:
    return [
        AdminPipelineEventItem(
            id=str(r.id),
            conversation_id=str(r.conversation_id),
            event_type=r.event_type,
            transcript_id=r.transcript_id,
            detail=r.detail if isinstance(r.detail, dict) else None,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/pipeline-events/wait", response_model=AdminPipelineEventsWaitResponse)
async def wait_pipeline_events(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
    q: Annotated[PipelineEventsWaitQueryParams, Depends(parse_pipeline_events_wait_query)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Long polling: block until new pipeline_events after (since_created_at, since_id) or timeout.
    Does not log each wait to admin_audit (would flood); use list endpoint for audited snapshots.
    """
    logger.debug(
        "pipeline_events_wait user_id=%s timeout=%s",
        principal.user.id,
        q.timeout_seconds,
    )
    et = q.event_type.strip() if isinstance(q.event_type, str) and q.event_type.strip() else None
    deadline = time.monotonic() + float(q.timeout_seconds)
    since_at = q.since_created_at
    if since_at.tzinfo is None:
        since_at = since_at.replace(tzinfo=timezone.utc)
    since_uuid = q.since_id
    while time.monotonic() < deadline:
        db.expire_all()
        rows = list_pipeline_events_newer_than(
            db,
            since_created_at=since_at,
            since_id=since_uuid,
            conversation_id=q.conversation_id,
            event_type=et,
            limit=50,
        )
        if rows:
            return AdminPipelineEventsWaitResponse(
                items=_pipeline_event_rows_to_items(rows),
                timed_out=False,
            )
        await asyncio.sleep(1.0)
    return AdminPipelineEventsWaitResponse(items=[], timed_out=True)


@router.get("/conversations", response_model=AdminConversationListResponse)
async def list_conversations(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
    q: Annotated[ListConversationsQueryParams, Depends(parse_list_conversations_query)],
    db: Annotated[Session, Depends(get_db)],
):
    _record_deduped_admin_read_audit(
        principal,
        action="conversations_list_view",
        detail=json.dumps(q.model_dump(), default=str, sort_keys=True),
    )
    total = count_admin_conversations(
        db,
        user_id=q.user_id,
        transcript_status=q.transcript_status,
        transcript_kind=q.transcript_kind,
        session_summary_status=q.session_summary_status,
        session_summary_missing=q.session_summary_missing,
        has_audio=q.has_audio,
        recording_session_id=q.recording_session_id,
    )
    rows = list_admin_conversations(
        db,
        user_id=q.user_id,
        transcript_status=q.transcript_status,
        transcript_kind=q.transcript_kind,
        session_summary_status=q.session_summary_status,
        session_summary_missing=q.session_summary_missing,
        has_audio=q.has_audio,
        recording_session_id=q.recording_session_id,
        limit=q.limit,
        offset=q.offset,
    )
    items: list[AdminConversationListItem] = []
    for row in rows:
        c = row.conversation
        at = row.active_transcript
        rss = row.recording_session_summary
        items.append(
            AdminConversationListItem(
                id=str(c.id),
                user_id=str(c.user_id),
                created_at=c.created_at,
                updated_at=c.updated_at,
                expires_at=c.expires_at,
                audio_uploaded_at=c.audio_uploaded_at,
                audio_object_ext=c.audio_object_ext,
                recording_session_id=str(c.recording_session_id),
                active_transcript_id=at.id if at else None,
                active_transcript_revision=at.revision if at else None,
                active_transcript_kind=at.kind if at else None,
                active_transcript_status=at.status if at else None,
                transcript_revision_count=row.transcript_count,
                session_summary_status=rss.status if rss else None,
                session_summary_error=_truncate_admin_pipeline_text(
                    rss.error if rss else None
                ),
                asr_chunk_completed=row.asr_chunk_completed,
                asr_chunk_total=row.asr_chunk_total,
            )
        )
    return AdminConversationListResponse(
        items=items, total=total, limit=q.limit, offset=q.offset
    )


@router.get("/conversations/{conversation_id}", response_model=AdminConversationDetailResponse)
async def conversation_detail(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
    db: Annotated[Session, Depends(get_db)],
    conversation_id: UUID,
):
    conv = get_conversation_for_admin(db, conversation_id)
    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    tmpl = app_config.admin_console.product_conversation_url_template
    product_url: str | None = None
    if tmpl and "{conversation_id}" in tmpl:
        product_url = tmpl.replace("{conversation_id}", str(conv.id))

    trs = list_transcripts_for_conversation(db, conv.id)
    transcripts = [
        AdminTranscriptRevision(
            id=t.id,
            revision=t.revision,
            kind=t.kind,
            status=t.status,
            created_at=t.created_at,
            updated_at=t.updated_at,
            meta=sanitize_transcript_meta(t.meta if isinstance(t.meta, dict) else None),
            asr_chunk_completed=t.asr_chunk_completed,
            asr_chunk_total=t.asr_chunk_total,
        )
        for t in trs
    ]

    rss = get_recording_session_summary_row(db, conv.recording_session_id)
    rss_out: AdminRecordingSessionSummarySlice | None = None
    if rss is not None:
        err = (rss.error or "").strip()
        if len(err) > 2000:
            err = err[:1999] + "…"
        rss_out = AdminRecordingSessionSummarySlice(
            recording_session_id=str(rss.recording_session_id),
            status=rss.status,
            error=err or None,
            meta=sanitize_transcript_meta(rss.meta if isinstance(rss.meta, dict) else None),
            created_at=rss.created_at,
            updated_at=rss.updated_at,
        )

    emb_rows = list_embeddings_for_conversation(db, conv.id)
    emb_out: list[AdminEmbeddingSlice] = []
    for e in emb_rows:
        dim = 0
        if isinstance(e.vector, list):
            dim = len(e.vector)
        emb_out.append(
            AdminEmbeddingSlice(
                id=e.id,
                transcript_id=e.transcript_id,
                kind=e.kind,
                created_at=e.created_at,
                vector_dimension=dim,
            )
        )

    try:
        record_admin_audit_event(
            admin_user_id=principal.user.id,
            action="conversation_view",
            conversation_id=conversation_id,
        )
    except Exception:
        logger.warning("admin audit persist failed (conversation_view)", exc_info=True)

    return AdminConversationDetailResponse(
        id=str(conv.id),
        user_id=str(conv.user_id),
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        expires_at=conv.expires_at,
        audio_uploaded_at=conv.audio_uploaded_at,
        audio_object_ext=conv.audio_object_ext,
        recording_session_id=str(conv.recording_session_id),
        previous_conversation_id=(
            str(conv.previous_conversation_id) if conv.previous_conversation_id else None
        ),
        client_realtime_mode=conv.client_realtime_mode,
        client_chunk_ms=conv.client_chunk_ms,
        active_transcript_id=conv.active_transcript_id,
        product_conversation_url=product_url,
        transcripts=transcripts,
        recording_session_summary=rss_out,
        embeddings=emb_out,
    )


@router.post("/conversations/{conversation_id}/actions/retranscribe", status_code=status.HTTP_202_ACCEPTED)
async def action_retranscribe(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
    db: Annotated[Session, Depends(get_db)],
    conversation_id: UUID,
):
    return admin_enqueue_retranscribe(db, principal, conversation_id)


@router.post(
    "/conversations/{conversation_id}/actions/reindex-embedding",
    status_code=status.HTTP_202_ACCEPTED,
)
async def action_reindex_embedding(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
    db: Annotated[Session, Depends(get_db)],
    conversation_id: UUID,
    transcript_id: Annotated[int | None, Query(description="Defaults to active ASR/diarized success")] = None,
):
    return admin_enqueue_embedding_reindex(db, principal, conversation_id, transcript_id)


@router.post(
    "/conversations/{conversation_id}/actions/rediarize",
    status_code=status.HTTP_202_ACCEPTED,
)
async def action_rediarize(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
    db: Annotated[Session, Depends(get_db)],
    conversation_id: UUID,
):
    return admin_enqueue_rediarize(db, principal, conversation_id)


@router.post(
    "/conversations/{conversation_id}/actions/resummary",
    status_code=status.HTTP_202_ACCEPTED,
)
async def action_resummary(
    principal: Annotated[AdminPrincipal, Depends(require_admin_principal)],
    db: Annotated[Session, Depends(get_db)],
    conversation_id: UUID,
):
    return admin_enqueue_resummary(db, principal, conversation_id)
