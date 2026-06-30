"""Speaker identify JSON parsing (C1.4)."""

from __future__ import annotations

import json

from core.speaker_labels import parse_speaker_identify_json


def test_parse_speaker_identify_json_strips_fence() -> None:
    raw = """```json
{"speakers": [{"speaker_id": "SPEAKER_00", "suggested_name": "Иван"}], "notes": ""}
```"""
    data = parse_speaker_identify_json(raw)
    assert data["speakers"][0]["suggested_name"] == "Иван"


def test_parse_speaker_identify_json_plain() -> None:
    payload = {"speakers": [], "notes": "ok"}
    assert parse_speaker_identify_json(json.dumps(payload)) == payload
