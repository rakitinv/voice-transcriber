"""Unit tests for core.speaker_labels (C1.4)."""

from __future__ import annotations

from core.speaker_labels import (
    apply_speaker_labels,
    collect_speaker_ids,
    effective_display_name,
    manual_label_entry,
    normalize_diarization_segments,
    parse_speaker_identify_json,
    rebuild_transcript_md,
)


def test_apply_speaker_labels_manual() -> None:
    segments = [
        {"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0, "text": "привет"},
        {"speaker": "SPEAKER_01", "start": 1.0, "end": 2.0, "text": "ответ"},
    ]
    labels = {
        "SPEAKER_00": manual_label_entry("Иван"),
        "SPEAKER_01": manual_label_entry("Мария"),
    }
    out = apply_speaker_labels(segments, labels)
    assert out[0]["speaker_id"] == "SPEAKER_00"
    assert out[0]["speaker"] == "Иван"
    assert out[1]["speaker"] == "Мария"


def test_llm_suggested_not_applied_until_confirmed() -> None:
    segments = [{"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0, "text": "x"}]
    labels = {
        "SPEAKER_00": {
            "display_name": "Иван",
            "source": "llm_suggested",
            "suggested_name": "Иван",
        }
    }
    out = apply_speaker_labels(segments, labels)
    assert out[0]["speaker"] == "SPEAKER_00"
    assert effective_display_name(labels["SPEAKER_00"]) is None


def test_normalize_diarization_sets_speaker_id() -> None:
    segs = normalize_diarization_segments(
        [{"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0, "text": "a"}],
        None,
    )
    assert segs[0]["speaker_id"] == "SPEAKER_00"
    assert segs[0]["speaker"] == "SPEAKER_00"


def test_rebuild_transcript_md_uses_display_names() -> None:
    md = rebuild_transcript_md(
        [
            {
                "speaker": "Иван",
                "speaker_id": "SPEAKER_00",
                "start": 12.0,
                "end": 15.2,
                "text": "текст",
            }
        ]
    )
    assert "**Иван** (12.0s–15.2s): текст" in md


def test_collect_speaker_ids_preserves_order() -> None:
    segments = [
        {"speaker": "SPEAKER_01", "text": "b"},
        {"speaker": "SPEAKER_00", "text": "a"},
        {"speaker": "SPEAKER_01", "text": "c"},
    ]
    assert collect_speaker_ids(segments) == ["SPEAKER_01", "SPEAKER_00"]


def test_parse_speaker_identify_json_in_core() -> None:
    data = parse_speaker_identify_json('{"speakers": [], "notes": "x"}')
    assert data["notes"] == "x"
