"""
Vosk: офлайн-модель из каталога (env `VOSK_MODEL_PATH` или `config["model_path"]`).
"""

from __future__ import annotations

import json
import os
import threading
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

from plugins.asr_base import ASRProvider, ASRSegment
from vosk import KaldiRecognizer, Model

from .audio_util import bytes_to_tempfile, media_to_wav_16k_mono

_models: dict[str, Model] = {}
_lock = threading.Lock()


class VoskASRProvider(ASRProvider):
    @property
    def name(self) -> str:
        return "vosk"

    def _model_dir(self) -> str:
        p = os.environ.get("VOSK_MODEL_PATH") or self.config.get("model_path")
        if not p:
            raise RuntimeError(
                "Vosk: set VOSK_MODEL_PATH to unpacked model directory "
                "(or model_path in configs/asr.yaml for vosk provider)"
            )
        path = Path(p).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Vosk model directory not found: {path}")
        return str(path)

    def _get_model(self) -> Model:
        d = self._model_dir()
        with _lock:
            if d not in _models:
                _models[d] = Model(d)
            return _models[d]

    def _transcribe_wav_path(self, wav_path: Path) -> str:
        model = self._get_model()
        rec = KaldiRecognizer(model, 16000)
        parts: list[str] = []
        with wave.open(str(wav_path), "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
                raise ValueError("Vosk expects 16-bit 16 kHz mono WAV")
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    j = json.loads(rec.Result())
                    t = (j.get("text") or "").strip()
                    if t:
                        parts.append(t)
            j = json.loads(rec.FinalResult())
            t = (j.get("text") or "").strip()
            if t:
                parts.append(t)
        return " ".join(parts).strip()

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        *,
        vad_preferences: Optional[dict] = None,
    ) -> List[ASRSegment]:
        wav = media_to_wav_16k_mono(audio_path)
        try:
            text = self._transcribe_wav_path(wav)
        finally:
            wav.unlink(missing_ok=True)
        if not text:
            return [ASRSegment(start=0.0, end=0.5, text="")]
        return [ASRSegment(start=0.0, end=1.0, text=text)]

    def transcribe_chunk(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
        *,
        vad_preferences: Optional[dict] = None,
    ) -> str:
        raw = bytes_to_tempfile(audio_data, ".webm")
        wav: Path | None = None
        try:
            wav = media_to_wav_16k_mono(raw)
            return self._transcribe_wav_path(wav)
        finally:
            raw.unlink(missing_ok=True)
            if wav is not None:
                wav.unlink(missing_ok=True)
