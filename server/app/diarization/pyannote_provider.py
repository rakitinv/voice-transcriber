from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logging import logger
from plugins.diarization_base import DiarizationProvider, DiarizationSegment


def _normalize_audio_to_wav_16k_mono(src_path: str) -> str:
    """
    Convert arbitrary input audio to a diarization-friendly WAV:
    - mono
    - 16kHz
    - PCM s16le
    """
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(src_path)

    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    out = Path(out_path)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(out),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg conversion failed: {stderr}") from e
    return str(out)


class PyannoteDiarizationProvider(DiarizationProvider):
    @property
    def name(self) -> str:
        return "pyannote"

    def _apply_offline_and_cache_env(self) -> None:
        cache_dir = (self.config.get("model_cache_dir") or "").strip()
        offline = bool(self.config.get("offline_models", False))

        if cache_dir:
            os.environ.setdefault("HF_HOME", cache_dir)
            os.environ.setdefault("HUGGINGFACE_HUB_CACHE", cache_dir)
            os.environ.setdefault("TRANSFORMERS_CACHE", cache_dir)

        if offline:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    def _apply_hf_token_env(self, hf_token: str) -> None:
        """
        huggingface_hub removed the legacy `use_auth_token=` kwarg in newer versions.
        Prefer passing the token via standard environment variables so downstream
        libraries can pick it up.
        """
        hf_token = (hf_token or "").strip()
        if not hf_token:
            return
        if not os.environ.get("HUGGINGFACE_HUB_TOKEN", "").strip():
            os.environ["HUGGINGFACE_HUB_TOKEN"] = hf_token
        if not os.environ.get("HF_TOKEN", "").strip():
            os.environ["HF_TOKEN"] = hf_token

    def run(
        self, audio_path: str, transcript_segments: Optional[List[Dict[str, Any]]] = None
    ) -> List[DiarizationSegment]:
        self._apply_offline_and_cache_env()

        model = (self.config.get("model") or "pyannote/speaker-diarization-3.1").strip()
        device_cfg = (self.config.get("device") or "auto").strip().lower()
        token_env = (self.config.get("hf_token_env") or "").strip()
        hf_token = os.environ.get(token_env, "").strip() if token_env else ""
        self._apply_hf_token_env(hf_token)

        offline = bool(self.config.get("offline_models", False))
        if not hf_token and not offline:
            # In online mode, token may still be required for gated models.
            logger.warning("HF token env %s is empty; pyannote model download may fail", token_env)

        if offline and not self.config.get("model_cache_dir"):
            raise RuntimeError("offline_models=true requires model_cache_dir to be set")

        try:
            from pyannote.audio import Pipeline  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "pyannote.audio import failed (образ воркера без группы diarization, "
                "сломанные torch/pyannote зависимости или не та сборка образа). "
                f"Причина: {type(e).__name__}: {e}"
            ) from e
        try:
            import torch  # type: ignore
        except Exception as e:
            raise RuntimeError("torch is not installed") from e

        # PyTorch 2.6+ defaults `torch.load(weights_only=True)` for security.
        # Some pyannote checkpoints require allowlisting extra globals when using
        # weights-only loading. We only do this for trusted upstream models.
        add_safe = getattr(getattr(torch, "serialization", None), "add_safe_globals", None)
        if callable(add_safe):
            try:
                from torch.torch_version import TorchVersion  # type: ignore

                try:
                    import inspect
                    import pyannote.audio.core.task as task  # type: ignore

                    allow = [TorchVersion]
                    allow.extend(
                        [
                            obj
                            for obj in vars(task).values()
                            if inspect.isclass(obj) and getattr(obj, "__module__", "") == task.__name__
                        ]
                    )
                except Exception:
                    allow = [TorchVersion]
                add_safe(allow)
            except Exception:
                pass

        if device_cfg not in ("auto", "cpu", "cuda"):
            raise RuntimeError(f"Unsupported diarization device: {device_cfg}")
        if device_cfg == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("device=cuda requested but torch.cuda.is_available() is false")
        device = "cuda" if (device_cfg == "auto" and torch.cuda.is_available()) else device_cfg
        if device == "auto":
            device = "cpu"

        wav_path = _normalize_audio_to_wav_16k_mono(audio_path)
        try:
            pipe = Pipeline.from_pretrained(model)
            try:
                pipe.to(torch.device(device))
            except Exception as e:
                raise RuntimeError(f"Failed to move pyannote pipeline to device={device}") from e

            # Speaker constraints (optional).
            num_speakers = self.config.get("num_speakers")
            min_speakers = self.config.get("min_speakers")
            max_speakers = self.config.get("max_speakers")

            diar = pipe(
                wav_path,
                num_speakers=num_speakers,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )

            segments: List[DiarizationSegment] = []
            for turn, _, speaker in diar.itertracks(yield_label=True):
                segments.append(
                    DiarizationSegment(
                        speaker=str(speaker),
                        start=float(turn.start),
                        end=float(turn.end),
                    )
                )
            return segments
        finally:
            try:
                Path(wav_path).unlink(missing_ok=True)
            except Exception:
                pass

