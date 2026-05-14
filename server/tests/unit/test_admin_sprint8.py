"""Sprint 8: pipeline-events query forbid, ASR chunk fields on list, §9 key checks."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from admin_api.conversations_read import AdminConversationRow
from admin_api.dependencies import AdminPrincipal, require_admin_principal
from admin_api.main import create_app
from app.models import AdminMembership, User
from core.db import get_db


@pytest.fixture
def client_with_admin_override() -> TestClient:
    app = create_app()

    user = MagicMock()
    user.id = uuid4()
    user.email = "admin@example.com"

    membership = MagicMock()
    membership.roles = ["admin"]

    principal = AdminPrincipal(user=user, membership=membership)
    app.dependency_overrides[require_admin_principal] = lambda: principal

    def mock_get_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = mock_get_db

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_pipeline_events_wait_unknown_query_returns_422(client_with_admin_override: TestClient) -> None:
    r = client_with_admin_override.get(
        "/admin/api/v1/pipeline-events/wait?since_created_at=2020-01-01T00:00:00Z"
        "&since_id=00000000-0000-0000-0000-000000000001&bad=1"
    )
    assert r.status_code == 422


def test_pipeline_events_wait_401_without_bearer() -> None:
    app = create_app()
    client = TestClient(app)
    r = client.get(
        "/admin/api/v1/pipeline-events/wait?since_created_at=2020-01-01T00:00:00Z"
        "&since_id=00000000-0000-0000-0000-000000000001"
    )
    assert r.status_code == 401


def test_pipeline_events_wait_returns_json(client_with_admin_override: TestClient) -> None:
    with patch("admin_api.routers.v1.list_pipeline_events_newer_than", return_value=[]):
        r = client_with_admin_override.get(
            "/admin/api/v1/pipeline-events/wait?since_created_at=2020-01-01T00:00:00Z"
            "&since_id=00000000-0000-0000-0000-000000000001&timeout_seconds=1"
        )
    assert r.status_code == 200
    body = r.json()
    assert body.get("timed_out") is True
    assert body.get("items") == []


def test_pipeline_events_unknown_query_returns_422(client_with_admin_override: TestClient) -> None:
    r = client_with_admin_override.get("/admin/api/v1/pipeline-events?limit=10&foo=1")
    assert r.status_code == 422


def test_pipeline_events_401_without_bearer() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.get("/admin/api/v1/pipeline-events?limit=5").status_code == 401


FORBIDDEN_PIPELINE_KEYS = frozenset(
    {
        "transcript_json",
        "transcript_md",
        "summary_md",
        "segments",
        "text",
        "vector",
    }
)


def _walk_keys(o: object, out: set[str]) -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(k, str):
                out.add(k)
            _walk_keys(v, out)
    elif isinstance(o, list):
        for x in o:
            _walk_keys(x, out)


def test_pipeline_events_list_json_shape(client_with_admin_override: TestClient) -> None:
    now = datetime.now(timezone.utc)
    cid = uuid4()

    ev = MagicMock()
    ev.id = uuid4()
    ev.conversation_id = cid
    ev.event_type = "asr_started"
    ev.transcript_id = 42
    ev.detail = {"transcript_id": 42}
    ev.created_at = now

    with patch("admin_api.routers.v1.count_pipeline_events", return_value=1):
        with patch("admin_api.routers.v1.list_pipeline_events", return_value=[ev]):
            r = client_with_admin_override.get("/admin/api/v1/pipeline-events?limit=10")
    assert r.status_code == 200
    body = r.json()
    keys: set[str] = set()
    _walk_keys(body, keys)
    assert keys.isdisjoint(FORBIDDEN_PIPELINE_KEYS)
    assert body["items"][0]["event_type"] == "asr_started"
    assert body["items"][0]["transcript_id"] == 42


def test_conversations_list_includes_asr_chunk_fields(client_with_admin_override: TestClient) -> None:
    now = datetime.now(timezone.utc)
    cid = uuid4()
    uid = uuid4()
    rsid = uuid4()

    c = MagicMock()
    c.id = cid
    c.user_id = uid
    c.created_at = now
    c.updated_at = now
    c.expires_at = None
    c.audio_uploaded_at = now
    c.audio_object_ext = "webm"
    c.recording_session_id = rsid

    at = MagicMock()
    at.id = 9
    at.revision = 2
    at.kind = "asr_diarized"
    at.status = "success"

    rss = MagicMock()
    rss.status = None
    rss.error = None

    row = AdminConversationRow(
        c, at, rss, 4, asr_chunk_completed=3, asr_chunk_total=10
    )

    with patch("admin_api.routers.v1.count_admin_conversations", return_value=1):
        with patch("admin_api.routers.v1.list_admin_conversations", return_value=[row]):
            r = client_with_admin_override.get("/admin/api/v1/conversations?limit=10")
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["asr_chunk_completed"] == 3
    assert item["asr_chunk_total"] == 10


def test_pipeline_events_403_without_admin_membership() -> None:
    app = create_app()
    uid = uuid4()
    fake_user = MagicMock()
    fake_user.id = uid

    mock_db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        filt = MagicMock()
        if model is User:
            filt.first.return_value = fake_user
        elif model is AdminMembership:
            filt.first.return_value = None
        else:
            filt.first.return_value = None
        chain.filter.return_value = filt
        return chain

    mock_db.query.side_effect = query_side_effect

    def mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = mock_get_db
    try:
        with patch("admin_api.dependencies.decode_access_token", return_value={"sub": str(uid)}):
            client = TestClient(app)
            r = client.get(
                "/admin/api/v1/pipeline-events?limit=5",
                headers={"Authorization": "Bearer fake"},
            )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()
