"""Sprint 3 Admin API: audit events list, rediarize."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from admin_api.dependencies import AdminPrincipal, require_admin_principal
from admin_api.main import create_app
from core.config import app_config


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
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_audit_events_requires_auth() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.get("/admin/api/v1/audit-events").status_code == 401


@patch("admin_api.routers.v1.list_admin_audit_events", return_value=[])
@patch("admin_api.routers.v1.count_admin_audit_events", return_value=0)
def test_audit_events_ok_shape(
    _mock_count: MagicMock,
    _mock_list: MagicMock,
    client_with_admin_override: TestClient,
) -> None:
    r = client_with_admin_override.get("/admin/api/v1/audit-events?limit=10&offset=0")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["limit"] == 10
    assert data["offset"] == 0
    assert set(data.keys()) == {"items", "total", "limit", "offset"}


def test_rediarize_requires_auth() -> None:
    app = create_app()
    client = TestClient(app)
    cid = "00000000-0000-4000-8000-000000000001"
    assert client.post(f"/admin/api/v1/conversations/{cid}/actions/rediarize").status_code == 401


def test_rediarize_accepted(client_with_admin_override: TestClient) -> None:
    cid = "00000000-0000-4000-8000-000000000000"
    conv = MagicMock()
    conv.user_id = uuid4()

    with patch.object(app_config, "diarization", replace(app_config.diarization, enabled=True)):
        with patch(
            "admin_api.pipeline_actions.get_conversation_for_admin", return_value=conv
        ) as _g:
            with patch(
                "admin_api.pipeline_actions.has_running_diarization_job", return_value=False
            ):
                with patch("admin_api.celery_bridge.send_pipeline_task") as send_task:
                    with patch("admin_api.pipeline_actions.record_admin_audit_event"):
                        r = client_with_admin_override.post(
                            f"/admin/api/v1/conversations/{cid}/actions/rediarize"
                        )
                        assert r.status_code == 202
                        assert r.json().get("status") == "accepted"
                        send_task.assert_called_once()
