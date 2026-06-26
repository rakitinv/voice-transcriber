"""Unit tests for pyannote 3.x / 4.x pipeline output handling."""

from __future__ import annotations

from app.diarization.pyannote_provider import (
    _annotation_from_pipeline_output,
    _iter_labeled_turns,
)


class _Turn:
    def __init__(self, start: float, end: float) -> None:
        self.start = start
        self.end = end


class _Annotation:
    def __init__(self, rows: list[tuple[float, float, str]]) -> None:
        self._rows = rows

    def itertracks(self, yield_label: bool = False):
        assert yield_label
        for start, end, speaker in self._rows:
            yield _Turn(start, end), None, speaker


class _DiarizeOutput:
    def __init__(self, annotation: _Annotation) -> None:
        self.speaker_diarization = annotation


def test_annotation_from_pipeline_output_legacy() -> None:
    ann = _Annotation([(0.0, 1.0, "A")])
    assert _annotation_from_pipeline_output(ann) is ann


def test_annotation_from_pipeline_output_v4() -> None:
    ann = _Annotation([(1.0, 2.5, "SPEAKER_00")])
    out = _DiarizeOutput(ann)
    assert _annotation_from_pipeline_output(out) is ann


def test_iter_labeled_turns_v4() -> None:
    out = _DiarizeOutput(_Annotation([(0.5, 3.0, "SPEAKER_01")]))
    rows = list(_iter_labeled_turns(out))
    assert len(rows) == 1
    turn, _track, speaker = rows[0]
    assert turn.start == 0.5
    assert turn.end == 3.0
    assert speaker == "SPEAKER_01"
