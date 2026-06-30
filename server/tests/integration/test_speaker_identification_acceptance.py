"""
C1.4 acceptance: manual rename (S1) + apply LLM suggestions (S2) via product API.

In-process (рекомендуется, код с диска + Postgres):

  set VT_DATABASE_URL=postgresql+psycopg2://voice:voice@127.0.0.1:5435/voice
  set VT_S3_ENDPOINT=http://127.0.0.1:9012
  set VT_S3_ACCESS_KEY=minioadmin
  set VT_S3_SECRET_KEY=minioadmin
  cd server
  poetry run pytest tests/integration/test_speaker_identification_acceptance.py -v -m speaker_acceptance

Против поднятого API (после rebuild образа с C1.4):

  set VT_E2E_BASE_URL=http://127.0.0.1:8002
  set VT_E2E_TOKEN=<JWT>
  poetry run pytest ... -m speaker_acceptance
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.main import app
from app.models import Conversation, Transcript, User
from core.config import app_config
from core.db import SessionLocal, get_db, session_scope
from core.security import create_access_token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def acceptance_mode() -> dict[str, Any]:
    db_url = (os.environ.get("VT_DATABASE_URL") or "").strip()
    base = (os.environ.get("VT_E2E_BASE_URL") or "").strip().rstrip("/")
    token = (os.environ.get("VT_E2E_TOKEN") or "").strip()
    if db_url:
        return {"mode": "inprocess", "base": "", "token": token}
    if base:
        if not token:
            pytest.skip("Set VT_E2E_TOKEN for HTTP acceptance")
        return {"mode": "http", "base": base, "token": token}
    pytest.skip("Set VT_DATABASE_URL (in-process) or VT_E2E_BASE_URL+TOKEN (HTTP)")


@pytest.fixture(scope="module")
def api_client(acceptance_mode: dict[str, Any]) -> Generator[TestClient | None, None, None]:
    if acceptance_mode["mode"] != "inprocess":
        yield None
        return

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def _seed_diarized_conversation() -> tuple[str, str, uuid.UUID, str]:
    """Return (conversation_id, jwt, user_id, email)."""
    uid = uuid.uuid4()
    cid = uuid.uuid4()
    email = f"speaker-acc-{uid.hex[:8]}@example.com"
    with session_scope() as db:
        user = User(id=uid, email=email, auth_provider="test")
        conv = Conversation(
            id=cid,
            user_id=uid,
            title="Speaker acceptance",
            s3_prefix=f"users/{uid}/{cid}",
            recording_session_id=cid,
            audio_uploaded_at=datetime.now(timezone.utc),
        )
        tr = Transcript(
            conversation_id=cid,
            user_id=uid,
            revision=1,
            kind="asr_diarized",
            status="success",
            transcript_json={
                "segments": [
                    {
                        "speaker_id": "SPEAKER_00",
                        "speaker": "SPEAKER_00",
                        "start": 0.0,
                        "end": 2.0,
                        "text": "меня зовут Иван, добрый день",
                    },
                    {
                        "speaker_id": "SPEAKER_01",
                        "speaker": "SPEAKER_01",
                        "start": 2.0,
                        "end": 4.0,
                        "text": "здравствуйте, я оператор",
                    },
                ]
            },
            transcript_md=(
                "**SPEAKER_00** (0.0s–2.0s): меня зовут Иван, добрый день\n\n"
                "**SPEAKER_01** (2.0s–4.0s): здравствуйте, я оператор"
            ),
        )
        db.add(user)
        db.add(conv)
        db.add(tr)
        db.flush()
        conv.active_transcript_id = tr.id
    jwt = create_access_token(data={"sub": str(uid)})
    return str(cid), jwt, uid, email


def _bind_user(user_id: uuid.UUID, email: str = "test@example.com") -> None:
    user = MagicMock(spec=User)
    user.id = user_id
    user.email = email
    user.preferences = {}
    app.dependency_overrides[get_current_user] = lambda: user


class _Http:
    def __init__(self, base: str, token: str):
        self._base = base
        self._token = token
        self._client = httpx.Client(timeout=httpx.Timeout(60.0), trust_env=True)

    def get(self, path: str, **kwargs):
        headers = {**_auth(self._token), **(kwargs.pop("headers", {}) or {})}
        return self._client.get(f"{self._base}{path}", headers=headers, **kwargs)

    def patch(self, path: str, **kwargs):
        headers = {**_auth(self._token), **(kwargs.pop("headers", {}) or {})}
        return self._client.patch(f"{self._base}{path}", headers=headers, **kwargs)

    def post(self, path: str, **kwargs):
        headers = {**_auth(self._token), **(kwargs.pop("headers", {}) or {})}
        return self._client.post(f"{self._base}{path}", headers=headers, **kwargs)

    def close(self) -> None:
        self._client.close()


def _client_for(
    acceptance_mode: dict[str, Any],
    api_client: TestClient | None,
    token: str,
    user_id: uuid.UUID,
    email: str,
):
    if acceptance_mode["mode"] == "inprocess":
        assert api_client is not None
        _bind_user(user_id, email)
        return api_client
    return _Http(acceptance_mode["base"], token)


def _resp_json(r) -> dict:
    if hasattr(r, "json"):
        return r.json()
    return json.loads(r.text)


@pytest.mark.speaker_acceptance
def test_s1_manual_rename_and_export(
    acceptance_mode: dict[str, Any], api_client: TestClient | None
) -> None:
    """S1: PATCH speakers → GET + export md contain display name «Иван»."""
    cid, token, uid, email = _seed_diarized_conversation()
    client = _client_for(acceptance_mode, api_client, token, uid, email)
    try:
        gr = client.get(f"/api/conversations/{cid}/speakers")
        assert gr.status_code == 200, getattr(gr, "text", gr)
        assert "SPEAKER_00" in (_resp_json(gr).get("speaker_ids") or [])

        pr = client.patch(
            f"/api/conversations/{cid}/speakers",
            json={"speakers": [{"speaker_id": "SPEAKER_00", "display_name": "Иван"}]},
        )
        assert pr.status_code == 200, getattr(pr, "text", pr)
        patched = _resp_json(pr)
        assert patched["speaker_labels"]["SPEAKER_00"]["display_name"] == "Иван"
        assert patched["speaker_labels"]["SPEAKER_00"]["source"] == "manual"

        detail = client.get(f"/api/conversations/{cid}", params={"tier": "final"})
        assert detail.status_code == 200
        segs = _resp_json(detail).get("transcript") or []
        spk00 = next((s for s in segs if s.get("speaker_id") == "SPEAKER_00"), None)
        assert spk00 is not None
        assert spk00["speaker"] == "Иван"

        er = client.get(
            f"/api/conversations/{cid}/export",
            params={"format": "md", "tier": "final"},
        )
        assert er.status_code == 200
        md = er.text if hasattr(er, "text") else er.content.decode()
        assert "**Иван**" in md

        jr = client.get(
            f"/api/conversations/{cid}/export",
            params={"format": "json", "tier": "final"},
        )
        assert jr.status_code == 200
        jbody = _resp_json(jr)
        meta = jbody.get("_meta") or {}
        assert "speaker_labels" in meta
        seg0 = (jbody.get("segments") or [])[0]
        assert seg0.get("speaker_id") == "SPEAKER_00"
        assert seg0.get("speaker") == "Иван"
    finally:
        if isinstance(client, _Http):
            client.close()


@pytest.mark.speaker_acceptance
def test_s2_apply_llm_suggestions_via_api(
    acceptance_mode: dict[str, Any], api_client: TestClient | None
) -> None:
    """S2: seed llm_suggested label → apply-suggestions → display updates."""
    cid, token, uid, email = _seed_diarized_conversation()
    with session_scope() as db:
        conv = db.query(Conversation).filter(Conversation.id == uuid.UUID(cid)).first()
        assert conv is not None
        conv.speaker_labels = {
            "SPEAKER_01": {
                "suggested_name": "Оператор",
                "display_name": "Оператор",
                "source": "llm_suggested",
                "confidence": 0.85,
                "evidence": "я оператор",
            }
        }
        conv.speaker_identification_status = "success"

    client = _client_for(acceptance_mode, api_client, token, uid, email)
    try:
        ar = client.post(
            f"/api/conversations/{cid}/speakers/apply-suggestions",
            json={"speaker_ids": ["SPEAKER_01"]},
        )
        assert ar.status_code == 200, getattr(ar, "text", ar)
        applied = _resp_json(ar)
        assert applied["speaker_labels"]["SPEAKER_01"]["display_name"] == "Оператор"

        detail = client.get(f"/api/conversations/{cid}", params={"tier": "final"})
        assert detail.status_code == 200
        segs = _resp_json(detail).get("transcript") or []
        spk01 = next((s for s in segs if s.get("speaker_id") == "SPEAKER_01"), None)
        assert spk01 is not None
        assert spk01["speaker"] == "Оператор"
    finally:
        if isinstance(client, _Http):
            client.close()


@pytest.mark.speaker_acceptance
def test_limits_exposes_speaker_identification_flag(
    acceptance_mode: dict[str, Any], api_client: TestClient | None
) -> None:
    """Feature flag visible in GET /api/settings/limits."""
    _, token, uid, email = _seed_diarized_conversation()
    client = _client_for(acceptance_mode, api_client, token, uid, email)
    try:
        r = client.get("/api/settings/limits")
        assert r.status_code == 200, getattr(r, "text", r)
        data = _resp_json(r)
        assert "speaker_identification_enabled" in data
        cfg = app_config.llm.speaker_identification
        expected = cfg.enabled and cfg.mode != "off"
        assert data["speaker_identification_enabled"] is expected
    finally:
        if isinstance(client, _Http):
            client.close()
