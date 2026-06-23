"""Unit tests for GigaAM ASR provider (mocked; no torch weights)."""

from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.asr.factory import ENGINE_NAMES, _provider_class, build_asr_provider
from app.asr.gigaam import GigaAMASRProvider
from app.asr import gigaam_engine


def _write_short_wav(path: Path, *, seconds: float = 1.0, rate: int = 16000) -> None:
    nframes = int(rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * nframes)


def test_gigaam_registered_in_factory() -> None:
    assert "gigaam" in ENGINE_NAMES
    assert _provider_class("gigaam") is GigaAMASRProvider
    p = build_asr_provider("gigaam", {"model": "v3_e2e_rnnt"})
    assert isinstance(p, GigaAMASRProvider)
    assert p.name == "gigaam"


def test_short_wav_transcribe_segments() -> None:
    fake_model = MagicMock()
    fake_model.transcribe.return_value = "привет мир"

    with patch.object(gigaam_engine, "get_gigaam_model", return_value=fake_model):
        tmp = Path(__file__).parent / "_gigaam_test_short.wav"
        try:
            _write_short_wav(tmp, seconds=2.0)
            segs = gigaam_engine.transcribe_wav_to_segments(
                tmp, {"model": "v3_e2e_rnnt", "longform_enabled": False}
            )
        finally:
            tmp.unlink(missing_ok=True)

    assert len(segs) == 1
    assert segs[0].text == "привет мир"
    assert segs[0].end >= 1.9
    fake_model.transcribe.assert_called_once()


def test_long_audio_uses_longform_when_enabled() -> None:
    fake_model = MagicMock()
    fake_model.transcribe_longform.return_value = [
        SimpleNamespace(start=0.0, end=5.0, text="первая"),
        SimpleNamespace(start=5.0, end=10.0, text="вторая"),
    ]

    with patch.object(gigaam_engine, "get_gigaam_model", return_value=fake_model):
        tmp = Path(__file__).parent / "_gigaam_test_long.wav"
        try:
            _write_short_wav(tmp, seconds=30.0)
            segs = gigaam_engine.transcribe_wav_to_segments(
                tmp,
                {"model": "v3_e2e_rnnt", "longform_enabled": True, "hf_token_env": "VT_HF_TOKEN"},
            )
        finally:
            tmp.unlink(missing_ok=True)

    assert len(segs) == 2
    assert segs[0].text == "первая"
    fake_model.transcribe_longform.assert_called_once()
    fake_model.transcribe.assert_not_called()


def test_long_audio_falls_back_to_chunking_when_longform_fails() -> None:
    fake_model = MagicMock()
    fake_model.transcribe_longform.side_effect = RuntimeError("no longform deps")
    fake_model.transcribe.return_value = "кусок"

    with patch.object(gigaam_engine, "get_gigaam_model", return_value=fake_model):
        with patch.object(gigaam_engine, "_slice_wav") as slice_mock:
            clip = Path(__file__).parent / "_gigaam_clip.wav"
            _write_short_wav(clip, seconds=20.0)
            slice_mock.return_value = clip
            tmp = Path(__file__).parent / "_gigaam_test_long2.wav"
            try:
                _write_short_wav(tmp, seconds=30.0)
                segs = gigaam_engine.transcribe_wav_to_segments(
                    tmp,
                    {"model": "v3_e2e_rnnt", "longform_enabled": True},
                )
            finally:
                tmp.unlink(missing_ok=True)
                clip.unlink(missing_ok=True)

    assert len(segs) >= 1
    assert any(s.text == "кусок" for s in segs)
    fake_model.transcribe_longform.assert_called_once()
    assert fake_model.transcribe.call_count >= 1


def test_provider_transcribe_chunk_delegates(tmp_path: Path) -> None:
    provider = GigaAMASRProvider({"model": "v3_e2e_rnnt"})
    wav = tmp_path / "c.wav"
    _write_short_wav(wav, seconds=1.0)

    with patch(
        "app.asr.gigaam.transcribe_bytes_to_text",
        return_value="тест",
    ) as mock_chunk:
        text = provider.transcribe_chunk(wav.read_bytes(), language="ru")
    assert text == "тест"
    mock_chunk.assert_called_once()
