"""
Проверка без импорта workers (иначе при collection поднимается S3/Celery).

Согласованность с e2e: см. test_phase_a_upload_export_e2e.py (маркер [stub ASR]).
"""

from __future__ import annotations

from pathlib import Path


def test_asr_stub_marker_present_in_source() -> None:
    asr_py = Path(__file__).resolve().parents[2] / "workers" / "tasks" / "asr.py"
    text = asr_py.read_text(encoding="utf-8")
    assert "STUB_TRANSCRIPT" in text
    assert "[stub ASR]" in text
