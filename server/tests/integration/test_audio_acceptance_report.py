"""
Запускает scripts/audio_acceptance_report.py против поднятого стека (как A3.2 e2e).

Проверяет upload→tier/export инварианты; realtime WS опционально через VT_E2E_REALTIME_WEBM.

  cd server
  set VT_E2E_BASE_URL=http://127.0.0.1:8002
  set VT_E2E_TOKEN=<JWT>
  poetry run pytest tests/integration/test_audio_acceptance_report.py -v -m audio_acceptance
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "audio_acceptance_report.py"


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
@pytest.mark.audio_acceptance
def test_audio_acceptance_report_dummy_upload(e2e_env: dict[str, str]) -> None:
    env = os.environ.copy()
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--base-url",
            e2e_env["base"],
            "--token",
            e2e_env["token"],
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        pytest.fail(
            "audio_acceptance_report failed\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )


@pytest.mark.e2e
@pytest.mark.audio_acceptance
def test_audio_acceptance_report_with_optional_files(e2e_env: dict[str, str]) -> None:
    raw = (os.environ.get("VT_E2E_ACCEPTANCE_FILES") or "").strip()
    paths: list[str] = []
    if raw:
        sep = ";" if ";" in raw else ","
        paths = [p.strip() for p in raw.split(sep) if p.strip()]
    else:
        sample = Path(__file__).resolve().parents[1] / "sample-1.webm"
        if sample.is_file():
            paths = [str(sample)]

    if not paths:
        pytest.skip(
            "Set VT_E2E_ACCEPTANCE_FILES or add server/tests/sample-1.webm for file upload checks"
        )

    cmd = [
        sys.executable,
        str(SCRIPT),
        "--base-url",
        e2e_env["base"],
        "--token",
        e2e_env["token"],
        *paths,
    ]
    rt = (os.environ.get("VT_E2E_REALTIME_WEBM") or "").strip()
    if rt:
        cmd.extend(["--realtime-webm", rt])

    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=900,
    )
    if proc.returncode != 0:
        pytest.fail(
            "audio_acceptance_report (files) failed\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
