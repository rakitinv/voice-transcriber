"""Sprint 4 Admin API: audit on /me, pipeline-settings, queue_depth on infrastructure."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from admin_api.celery_monitor import QueueConsumerStatus
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


def test_me_records_audit(client_with_admin_override: TestClient) -> None:
    with patch("admin_api.routers.v1.record_admin_audit_event") as rec:
        r = client_with_admin_override.get("/admin/api/v1/me")
    assert r.status_code == 200
    rec.assert_called_once()
    kwargs = rec.call_args.kwargs
    assert kwargs.get("action") == "admin_console_session"


def test_me_requires_auth() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.get("/admin/api/v1/me").status_code == 401


def test_pipeline_settings_requires_auth() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.get("/admin/api/v1/pipeline-settings").status_code == 401


FORBIDDEN_SECRET_KEYS = frozenset(
    {
        "api_key",
        "openai_api_key",
        "client_secret",
        "secret_key",
        "access_key",
        "database",
        "redis",
        "password",
    }
)


def _collect_keys(obj: object, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                out.add(k)
            _collect_keys(v, out)
    elif isinstance(obj, list):
        for x in obj:
            _collect_keys(x, out)


def test_pipeline_settings_no_secret_keys(client_with_admin_override: TestClient) -> None:
    r = client_with_admin_override.get("/admin/api/v1/pipeline-settings")
    assert r.status_code == 200
    body = r.json()
    keys: set[str] = set()
    _collect_keys(body, keys)
    assert keys.isdisjoint(FORBIDDEN_SECRET_KEYS)
    assert "environment" in body
    assert "asr" in body and "providers" in body["asr"]


def test_infrastructure_queue_depth_field(client_with_admin_override: TestClient) -> None:
    fake = [
        QueueConsumerStatus(
            queue="asr",
            consumer_responding=False,
            queue_depth=3,
            detail="unit",
        ),
    ]
    with patch(
        "admin_api.routers.v1.get_queue_consumer_status_cached",
        return_value=fake,
    ):
        r = client_with_admin_override.get("/admin/api/v1/infrastructure")
    assert r.status_code == 200
    row = r.json()["celery_queues"][0]
    assert row["queue_depth"] == 3
    assert set(row.keys()) == {"queue", "consumer_responding", "queue_depth", "detail"}


def test_pipeline_settings_diarization_reflects_config(client_with_admin_override: TestClient) -> None:
    with patch.object(app_config, "diarization", replace(app_config.diarization, enabled=True)):
        r = client_with_admin_override.get("/admin/api/v1/pipeline-settings")
    assert r.status_code == 200
    assert r.json()["diarization"]["enabled"] is True
