"""
Smoke: diarization worker is optional and buildable.

We don't run diarization here (needs HF model downloads / token). This just ensures
the docker compose profile wiring and image build does not break the base stack.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_diarization_worker_builds_with_profile() -> None:
    repo = Path(__file__).resolve().parents[3]
    docker_dir = repo / "docker"
    if not docker_dir.is_dir():
        pytest.skip("docker/ dir not found")

    env = os.environ.copy()
    # Ensure build uses public PyPI for `lightning` (pyannote dependency) if host has a custom index.
    env.setdefault("PIP_INDEX_URL", "https://pypi.org/simple")

    proc = subprocess.run(
        ["docker", "compose", "--profile", "diarization", "build", "diarization-worker"],
        cwd=str(docker_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if proc.returncode != 0:
        pytest.fail(
            "Failed to build diarization-worker (compose profile diarization)\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )

