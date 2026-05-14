"""Smoke tests for Admin API app (no database)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from admin_api.main import create_app


def test_admin_public_health() -> None:
    app = create_app()
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "healthy"
    assert body.get("service") == "admin-api"


def test_admin_me_requires_auth() -> None:
    app = create_app()
    client = TestClient(app)
    r = client.get("/admin/api/v1/me")
    assert r.status_code == 401
