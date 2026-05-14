"""
Strip transcript ``meta`` fields that may carry conversation text (ADMIN_OPS_CONSOLE §9).
"""

from __future__ import annotations

import copy
from typing import Any

# Keys removed entirely ( subtree dropped ).
_META_DROP_KEYS = frozenset(
    {
        "text",
        "transcript",
        "transcript_text",
        "markdown",
        "md",
        "segments",
        "chunk_text",
        "chunks",
        "preview",
        "snippet",
        "initial_prompt",
        "hotwords",
    }
)


def _truncate_str(s: str, max_len: int) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def sanitize_transcript_meta(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a deep copy of ``meta`` safe for admin JSON (no segment bodies / long prose)."""
    if meta is None:
        return None
    if not isinstance(meta, dict):
        return None

    def walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for k, v in obj.items():
                lk = str(k).lower()
                if lk in _META_DROP_KEYS:
                    continue
                if lk == "error" and isinstance(v, str):
                    out[k] = _truncate_str(v, 500)
                    continue
                if isinstance(v, str) and len(v) > 4000:
                    out[k] = _truncate_str(v, 4000)
                    continue
                out[k] = walk(v)
            return out
        if isinstance(obj, list):
            return [walk(x) for x in obj]
        return obj

    return walk(copy.deepcopy(meta))
