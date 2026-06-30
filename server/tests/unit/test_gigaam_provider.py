"""Unit tests for GigaAM ASR provider (mocked; no torch weights)."""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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


def test_hf_revision_maps_v3_model_name() -> None:
    assert gigaam_engine._hf_revision("v3_e2e_rnnt") == "e2e_rnnt"
    assert gigaam_engine._hf_revision("e2e_rnnt") == "e2e_rnnt"


def test_gigaam_weights_source_auto_prefers_hf_for_v3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VT_GIGAAM_WEIGHTS_SOURCE", raising=False)
    assert gigaam_engine._gigaam_weights_source("v3_e2e_rnnt") == "hf"
    assert gigaam_engine._gigaam_weights_source("v1_rnnt") == "cdn"


def test_segments_from_longform_hf_dict_format() -> None:
    segs = gigaam_engine._segments_from_longform(
        [
            {"transcription": "привет", "boundaries": (0.0, 1.5)},
            {"transcription": "мир", "boundaries": (1.5, 3.0)},
        ]
    )
    assert len(segs) == 2
    assert segs[0].text == "привет"
    assert segs[0].start == 0.0
    assert segs[1].end == 3.0


def test_get_gigaam_model_uses_hf_loader_for_v3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_GIGAAM_WEIGHTS_SOURCE", "hf")
    gigaam_engine._model_cache.clear()
    fake = MagicMock()
    fake_mod = MagicMock()
    fake_mod.from_pretrained.return_value = fake
    fake_torch = MagicMock()
    fake_torch.cuda.is_available.return_value = False
    fake_torch.device = MagicMock(side_effect=lambda d: d)
    with (
        patch.object(gigaam_engine, "_load_gigaam_hf_model", return_value=fake) as load_hf,
        patch.dict("sys.modules", {"torch": fake_torch}),
    ):
        got = gigaam_engine.get_gigaam_model({"model": "v3_e2e_rnnt"})
    assert got is fake
    load_hf.assert_called_once()
    gigaam_engine._model_cache.clear()


def test_hf_from_pretrained_disables_meta_skeleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VT_HF_TOKEN", "hf_test")
    captured: dict[str, Any] = {}

    def _fake_from_pretrained(_repo: str, **kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        return MagicMock(eval=MagicMock(return_value=MagicMock()))

    fake_auto = MagicMock()
    fake_auto.from_pretrained.side_effect = _fake_from_pretrained
    fake_transformers = MagicMock()
    fake_transformers.AutoModel = fake_auto
    fake_torch = MagicMock()
    fake_torch.cuda.is_available.return_value = False

    with patch.dict("sys.modules", {"transformers": fake_transformers, "torch": fake_torch}):
        gigaam_engine._load_gigaam_hf_model(
            "v3_e2e_rnnt",
            {"hf_token_env": "VT_HF_TOKEN"},
            "cpu",
        )

    assert captured.get("low_cpu_mem_usage") is False
    assert captured.get("revision") == "e2e_rnnt"
    assert captured.get("trust_remote_code") is True
    assert captured.get("token") == "hf_test"
    assert "torch_dtype" not in captured


def test_load_gigaam_hf_model_uses_fp16_on_cuda(monkeypatch):
    monkeypatch.setenv("VT_HF_TOKEN", "hf_test")
    captured: dict[str, Any] = {}

    def _fake_from_pretrained(_repo: str, **kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        m = MagicMock()
        m.to.return_value = m
        m.eval.return_value = m
        return m

    fake_auto = MagicMock()
    fake_auto.from_pretrained.side_effect = _fake_from_pretrained
    fake_transformers = MagicMock()
    fake_transformers.AutoModel = fake_auto
    fake_torch = MagicMock()
    fake_torch.float16 = "float16"
    fake_torch.cuda.is_available.return_value = True

    with patch.dict("sys.modules", {"transformers": fake_transformers, "torch": fake_torch}):
        gigaam_engine._load_gigaam_hf_model(
            "v3_e2e_rnnt",
            {"hf_token_env": "VT_HF_TOKEN"},
            "cuda",
        )

    assert captured.get("torch_dtype") == "float16"
