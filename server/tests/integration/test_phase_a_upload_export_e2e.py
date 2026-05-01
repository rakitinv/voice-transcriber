"""
A3.2: интеграционный / e2e сценарий — upload → обработка (stub ASR) → экспорт транскрипта.

Проверяет основную цепочку «аудио → текст» при включённом stub-провайдере ASR (Phase A).

Запуск (подняты api, worker, postgres, redis, minio; JWT пользователя с записью в БД):

  set VT_E2E_BASE_URL=http://127.0.0.1:8002
  set VT_E2E_TOKEN=<JWT из Web UI localStorage access_token>
  cd server
  poetry run pytest tests/integration/test_phase_a_upload_export_e2e.py -v -m e2e

Без переменных тесты помечены skip (не ломают локальный pytest без стека).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest

# Минимальные байты WebM — совместимо с phase_a_upload_smoke / stub ASR
DUMMY_WEBM: bytes = b"\x1a\x45\xdf\xa3" + b"\x00" * 512


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def e2e_env() -> dict[str, str]:
    base = (os.environ.get("VT_E2E_BASE_URL") or "").strip().rstrip("/")
    token = (os.environ.get("VT_E2E_TOKEN") or "").strip()
    if not base or not token:
        pytest.skip(
            "E2E: set VT_E2E_BASE_URL (e.g. http://127.0.0.1:8002) and VT_E2E_TOKEN (JWT)"
        )
    return {"base": base, "token": token}


@pytest.mark.e2e
def test_upload_poll_export_md_contains_stub_text(e2e_env: dict[str, str]) -> None:
    """
    POST /api/upload → poll GET /api/conversations/{id} → GET export format=md.

    Ожидается placeholder-транскрипт: классический stub ([stub ASR]) или wired (B1.5).
    """
    base = e2e_env["base"]
    token = e2e_env["token"]
    interval = float(os.environ.get("VT_E2E_POLL_INTERVAL", "2"))
    max_wait = float(os.environ.get("VT_E2E_MAX_WAIT", "120"))

    timeout = httpx.Timeout(120.0, connect=30.0)
    with httpx.Client(timeout=timeout, trust_env=True) as client:
        files = {"file": ("e2e.webm", DUMMY_WEBM, "audio/webm")}
        r = client.post(
            f"{base}/api/upload",
            headers=_auth(token),
            files=files,
        )
        assert r.status_code == 202, f"upload: {r.status_code} {r.text}"
        body = r.json()
        cid = body.get("conversation_id")
        assert cid, body

        deadline = time.monotonic() + max_wait
        detail: dict | None = None
        while time.monotonic() < deadline:
            gr = client.get(
                f"{base}/api/conversations/{cid}",
                headers=_auth(token),
            )
            assert gr.status_code == 200, f"get conversation: {gr.status_code} {gr.text}"
            detail = gr.json()
            segs = detail.get("transcript") or []
            if len(segs) > 0:
                break
            time.sleep(interval)
        else:
            pytest.fail(
                f"Timeout {max_wait}s waiting for transcript. Last detail: {detail!r}"
            )

        er = client.get(
            f"{base}/api/conversations/{cid}/export",
            headers=_auth(token),
            params={"format": "md"},
        )
        assert er.status_code == 200, f"export: {er.status_code} {er.text}"
        md = er.text
        assert len(md) > 0
        assert (
            "[stub ASR]" in md
            or "placeholder transcript" in md.lower()
            or "[ASR wired]" in md
        ), md[:500]
