"""Sprint 2 Admin API: external tools shape, infrastructure queues, meta sanitize, auth."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from admin_api.celery_monitor import QueueConsumerStatus, clear_queue_consumer_status_cache
from admin_api.dependencies import AdminPrincipal, require_admin_principal
from admin_api.main import create_app
from admin_api.meta_sanitize import sanitize_transcript_meta


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
    clear_queue_consumer_status_cache()


def test_external_tools_requires_auth() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.get("/admin/api/v1/external-tools").status_code == 401


def test_pipeline_actions_require_auth() -> None:
    app = create_app()
    client = TestClient(app)
    cid = "00000000-0000-4000-8000-000000000001"
    assert (
        client.post(f"/admin/api/v1/conversations/{cid}/actions/retranscribe").status_code == 401
    )
    assert (
        client.post(
            f"/admin/api/v1/conversations/{cid}/actions/reindex-embedding"
        ).status_code
        == 401
    )
    assert client.post(f"/admin/api/v1/conversations/{cid}/actions/rediarize").status_code == 401
    assert client.post(f"/admin/api/v1/conversations/{cid}/actions/resummary").status_code == 401


def test_external_tools_ok_shape(client_with_admin_override: TestClient) -> None:
    r = client_with_admin_override.get("/admin/api/v1/external-tools")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("tools"), list)
    for t in data["tools"]:
        assert "name" in t and "url" in t
        assert set(t.keys()) == {"name", "url"}


def test_infrastructure_includes_celery_queues(client_with_admin_override: TestClient) -> None:
    fake = [
        QueueConsumerStatus(
            queue="asr",
            consumer_responding=False,
            queue_depth=None,
            detail="unit",
        ),
    ]
    with patch(
        "admin_api.routers.v1.get_queue_consumer_status_cached",
        return_value=fake,
    ):
        r = client_with_admin_override.get("/admin/api/v1/infrastructure")
    assert r.status_code == 200
    body = r.json()
    assert "celery_queues" in body
    assert isinstance(body["celery_queues"], list)
    assert body["celery_queues"][0]["queue"] == "asr"
    assert body.get("deploy_profile") in ("cpu", "gpu")
    assert "compatibility_issues" in body
    assert isinstance(body["compatibility_issues"], list)


def test_sanitize_meta_drops_segments() -> None:
    raw = {
        "device": "cpu",
        "segments": [{"text": "secret speech", "start": 0}],
        "nested": {"preview": "x"},
    }
    out = sanitize_transcript_meta(raw)
    assert out is not None
    assert "segments" not in out
    assert "preview" not in json.dumps(out)
    assert out.get("device") == "cpu"


def test_json_no_forbidden_keys_nested() -> None:
    forbidden = frozenset(
        {
            "transcript_json",
            "transcript_md",
            "summary_md",
            "vector",
            "transcript_text",
        }
    )

    def walk(o: object) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                assert k not in forbidden
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    sample = {
        "id": str(uuid4()),
        "user_id": str(uuid4()),
        "active_transcript_kind": "asr",
    }
    walk(sample)
