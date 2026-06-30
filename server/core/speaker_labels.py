"""Speaker display names: apply labels to diarized segments and rebuild transcript_md."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

APPLIED_SOURCES = frozenset({"manual", "llm_auto"})
PENDING_LLM_SOURCE = "llm_suggested"


def resolve_speaker_id(seg: dict[str, Any]) -> str:
    """Stable diarization key; legacy segments use ``speaker`` as id."""
    raw = seg.get("speaker_id")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    return str(seg.get("speaker", "Speaker 1")).strip() or "Speaker 1"


def collect_speaker_ids(segments: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        sid = resolve_speaker_id(seg)
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def effective_display_name(entry: dict[str, Any] | None) -> str | None:
    """Display name applied to segments (not pending LLM suggestions)."""
    if not isinstance(entry, dict):
        return None
    source = str(entry.get("source") or "").strip()
    if source == PENDING_LLM_SOURCE:
        return None
    if source in APPLIED_SOURCES or entry.get("applied") is True:
        name = entry.get("display_name")
        if name is not None and str(name).strip():
            return str(name).strip()
    if source == "diarization":
        name = entry.get("display_name")
        if name is not None and str(name).strip():
            return str(name).strip()
    return None


def apply_speaker_labels(
    segments: list[dict[str, Any]],
    speaker_labels: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return segments with ``speaker_id`` set and ``speaker`` as display name."""
    labels = speaker_labels if isinstance(speaker_labels, dict) else {}
    out: list[dict[str, Any]] = []
    for raw in segments:
        if not isinstance(raw, dict):
            continue
        seg = dict(raw)
        sid = resolve_speaker_id(seg)
        seg["speaker_id"] = sid
        entry = labels.get(sid)
        display = effective_display_name(entry if isinstance(entry, dict) else None)
        seg["speaker"] = display if display else sid
        out.append(seg)
    return out


def rebuild_transcript_md(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for seg in segments:
        sp = str(seg.get("speaker", "Speaker 1"))
        lines.append(
            f"**{sp}** ({float(seg.get('start', 0)):.1f}s–{float(seg.get('end', 0)):.1f}s): "
            f"{seg.get('text', '')}"
        )
    return "\n\n".join(lines) if lines else "_No transcript._\n"


def normalize_diarization_segments(
    segments: list[dict[str, Any]],
    speaker_labels: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Ensure speaker_id on fresh diarization output and apply known display names."""
    with_ids: list[dict[str, Any]] = []
    for raw in segments:
        if not isinstance(raw, dict):
            continue
        seg = dict(raw)
        pyannote_label = str(seg.get("speaker", "Speaker 1")).strip() or "Speaker 1"
        seg["speaker_id"] = pyannote_label
        seg["speaker"] = pyannote_label
        with_ids.append(seg)
    return apply_speaker_labels(with_ids, speaker_labels)


def participants_summary_block(speaker_labels: dict[str, Any] | None) -> str:
    """Markdown block for LLM summary prompts."""
    if not isinstance(speaker_labels, dict) or not speaker_labels:
        return ""
    lines: list[str] = []
    for sid, entry in speaker_labels.items():
        if not isinstance(entry, dict):
            continue
        name = effective_display_name(entry)
        if not name:
            continue
        role = entry.get("role")
        if role and str(role).strip():
            lines.append(f"- {name} ({sid}, {role})")
        else:
            lines.append(f"- {name} ({sid})")
    if not lines:
        return ""
    return "## Участники\n\n" + "\n".join(lines) + "\n\n"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_speaker_identify_json(raw: str) -> dict[str, Any]:
    import json
    import re

    text = (raw or "").strip()
    if not text:
        raise ValueError("empty_llm_response")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("speaker_identify_not_object")
    return data


def manual_label_entry(display_name: str, *, updated_by: str = "user") -> dict[str, Any]:
    return {
        "display_name": display_name.strip(),
        "source": "manual",
        "confidence": None,
        "updated_at": utc_now_iso(),
        "updated_by": updated_by,
    }


def llm_suggestion_entry(
    *,
    suggested_name: str | None,
    role: str | None,
    confidence: float | None,
    evidence: str | None,
) -> dict[str, Any]:
    return {
        "suggested_name": suggested_name,
        "display_name": suggested_name,
        "role": role,
        "confidence": confidence,
        "evidence": evidence,
        "source": PENDING_LLM_SOURCE,
        "updated_at": utc_now_iso(),
        "updated_by": "llm",
    }


def applied_llm_entry(
    display_name: str,
    *,
    role: str | None = None,
    confidence: float | None = None,
    source: str = "llm_auto",
) -> dict[str, Any]:
    return {
        "display_name": display_name.strip(),
        "source": source,
        "role": role,
        "confidence": confidence,
        "applied": True,
        "updated_at": utc_now_iso(),
        "updated_by": "llm",
    }
