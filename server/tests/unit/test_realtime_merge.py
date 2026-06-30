"""Tests for realtime partial merge."""

from core.realtime_merge import merge_realtime_partials


def test_merge_drops_overlap_prefix() -> None:
    entries = [
        {"start": 0.0, "end": 3.0, "text": "hello world"},
        {"start": 1.5, "end": 4.5, "text": "world again"},
    ]
    merged = merge_realtime_partials(entries, step_s=2.0, overlap_s=1.0)
    assert len(merged) == 2
    assert merged[0]["text"] == "hello world"
    assert merged[1]["start"] >= 1.0
