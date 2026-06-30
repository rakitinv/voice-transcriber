"""
Merge overlapping realtime ASR windows into transcript segments (REALTIME_FAST_FINAL_V2 §6.4).
"""

from __future__ import annotations


def merge_realtime_partials(
    entries: list[dict],
    *,
    step_s: float,
    overlap_s: float = 0.0,
) -> list[dict]:
    """
    Combine windowed partials with time bounds.

    Each entry: ``start``, ``end``, ``text``. Later windows may overlap earlier ones;
    segments ending before the hard step boundary are dropped (same idea as upload chunk merge).
    """
    if not entries:
        return []

    advance = max(float(step_s) - float(overlap_s), 0.05)
    segments: list[dict] = []
    for idx, raw in enumerate(entries):
        text = str(raw.get("text", "")).strip()
        if not text:
            continue
        try:
            st = float(raw.get("start", 0.0))
            en = float(raw.get("end", st))
        except (TypeError, ValueError):
            continue
        hard_t0 = idx * advance
        if idx > 0 and en <= hard_t0:
            continue
        seg_start = max(st, hard_t0) if idx > 0 else st
        segments.append(
            {
                "speaker": str(raw.get("speaker", "Speaker 1")),
                "start": seg_start,
                "end": max(en, seg_start + 0.05),
                "text": text,
            }
        )
    return segments
