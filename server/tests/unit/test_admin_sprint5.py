"""Sprint 5 Admin API: conversations list filters/extra forbid, §9 list shape, resummary."""

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
from core.config import app_config
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


def test_conversations_unknown_query_returns_422(client_with_admin_override: TestClient) -> None:
    r = client_with_admin_override.get("/admin/api/v1/conversations?limit=10&not_a_real_param=1")
    assert r.status_code == 422


def test_conversations_403_without_admin_membership() -> None:
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
                "/admin/api/v1/conversations?limit=5",
                headers={"Authorization": "Bearer fake"},
            )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()


FORBIDDEN_LIST_KEYS = frozenset(
    {
        "transcript_json",
        "transcript_md",
        "summary_md",
        "vector",
        "transcript_text",
        "segments",
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


def test_conversations_list_json_no_forbidden_keys(client_with_admin_override: TestClient) -> None:
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
    rss.status = "failed"
    rss.error = "upstream timeout"

    row = AdminConversationRow(c, at, rss, 4)

    with patch("admin_api.routers.v1.count_admin_conversations", return_value=1):
        with patch("admin_api.routers.v1.list_admin_conversations", return_value=[row]):
            r = client_with_admin_override.get("/admin/api/v1/conversations?limit=10")
    assert r.status_code == 200
    body = r.json()
    keys: set[str] = set()
    _walk_keys(body, keys)
    assert keys.isdisjoint(FORBIDDEN_LIST_KEYS)
    assert body["items"][0]["transcript_revision_count"] == 4
    assert body["items"][0]["session_summary_status"] == "failed"
    assert "timeout" in (body["items"][0].get("session_summary_error") or "")


def test_resummary_requires_auth() -> None:
    app = create_app()
    client = TestClient(app)
    cid = "00000000-0000-4000-8000-000000000001"
    assert client.post(f"/admin/api/v1/conversations/{cid}/actions/resummary").status_code == 401


def test_resummary_accepted(client_with_admin_override: TestClient) -> None:
    cid = "00000000-0000-4000-8000-000000000000"
    conv = MagicMock()
    conv.user_id = uuid4()
    conv.recording_session_id = uuid4()

    with patch.object(app_config.llm, "session_summary_enabled", True):
        with patch(
            "admin_api.pipeline_actions.get_conversation_for_admin", return_value=conv
        ):
            with patch(
                "admin_api.pipeline_actions.get_recording_session_summary_row",
                return_value=MagicMock(status="failed"),
            ):
                with patch(
                    "admin_api.pipeline_actions._admin_resummary_llm_provider",
                    return_value=object(),
                ):
                    with patch("admin_api.celery_bridge.send_pipeline_task") as sched:
                        with patch("admin_api.pipeline_actions.record_admin_audit_event"):
                            r = client_with_admin_override.post(
                                f"/admin/api/v1/conversations/{cid}/actions/resummary"
                            )
                            assert r.status_code == 202
                            assert r.json().get("status") == "accepted"
                            sched.assert_called_once()
                            assert sched.call_args.kwargs["queue"] == "llm"


def test_resummary_400_when_disabled(client_with_admin_override: TestClient) -> None:
    cid = "00000000-0000-4000-8000-000000000000"
    with patch.object(app_config.llm, "session_summary_enabled", False):
        r = client_with_admin_override.post(f"/admin/api/v1/conversations/{cid}/actions/resummary")
    assert r.status_code == 400
