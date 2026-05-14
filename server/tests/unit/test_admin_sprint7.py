"""Sprint 7: live-tick endpoint auth and §9-safe payload."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from admin_api.dependencies import AdminPrincipal, require_admin_principal
from admin_api.main import create_app
from app.models import AdminMembership, User
from core.db import get_db

FORBIDDEN_TICK_KEYS = frozenset(
    {
        "conversation_id",
        "user_id",
        "transcript",
        "segments",
        "transcript_json",
        "transcript_md",
        "summary_md",
        "audio",
        "presigned",
    }
)


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


def test_live_tick_401_without_bearer() -> None:
    app = create_app()
    client = TestClient(app)
    r = client.get("/admin/api/v1/live-tick")
    assert r.status_code == 401


def test_live_tick_403_without_admin_membership() -> None:
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
            r = client.get("/admin/api/v1/live-tick", headers={"Authorization": "Bearer x"})
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_live_tick_200_shape_and_no_forbidden_keys(client_with_admin_override: TestClient) -> None:
    r = client_with_admin_override.get("/admin/api/v1/live-tick")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"tick_ms", "schema_version"}
    assert isinstance(data["tick_ms"], int)
    assert data["schema_version"] == 1
    flat = " ".join(f"{k}={v}" for k, v in data.items()).lower()
    for bad in FORBIDDEN_TICK_KEYS:
        assert bad not in flat
