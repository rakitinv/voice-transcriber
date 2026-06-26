"""Parallel ASR chord merge (§17)."""

from __future__ import annotations

from workers.tasks.asr import _normalize_parallel_chunk_results


def test_normalize_parallel_chunk_results_none() -> None:
    out = _normalize_parallel_chunk_results([{"ok": True, "segments": []}, None])
    assert out[0]["ok"] is True
    assert out[1]["ok"] is False
    assert out[1]["error"] == "missing_chunk_result"


def test_normalize_parallel_chunk_results_invalid() -> None:
    out = _normalize_parallel_chunk_results(["bad"])
    assert out[0]["error"] == "invalid_chunk_result:str"
