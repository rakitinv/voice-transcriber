from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logging import logger
from plugins.diarization_base import DiarizationProvider, DiarizationSegment


def _annotation_from_pipeline_output(diar: Any) -> Any:
    """
    pyannote.audio 4.x returns DiarizeOutput; speaker segments are on
    .speaker_diarization (pyannote.core.Annotation). Older versions returned
    Annotation directly from pipeline(...).
    """
    ann = getattr(diar, "speaker_diarization", None)
    if ann is not None:
        return ann
    return diar


def _iter_labeled_turns(diar: Any):
    """Yield (turn, track, speaker) from pipeline output (3.x or 4.x)."""
    annotation = _annotation_from_pipeline_output(diar)
    if not hasattr(annotation, "itertracks"):
        raise RuntimeError(
            "Unexpected pyannote pipeline output: expected Annotation.itertracks "
            f"or DiarizeOutput.speaker_diarization, got {type(diar).__name__}"
        )
    yield from annotation.itertracks(yield_label=True)


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

        if device == "cpu" and torch.cuda.is_available():
            # In GPU images, from_pretrained may touch CUDA first; free VRAM before load/move.
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

        wav_path = _normalize_audio_to_wav_16k_mono(audio_path)
        try:
            pipe = Pipeline.from_pretrained(model)
            if pipe is None:
                raise RuntimeError(
                    f"pyannote Pipeline.from_pretrained({model!r}) returned None. "
                    "Обычно это gated-модель HuggingFace: задайте VT_HF_TOKEN в env воркера, "
                    "примите условия на https://hf.co/pyannote/speaker-diarization-3.1 "
                    "(и связанные pyannote/* модели), пересоздайте diarization-worker."
                )
            torch_dev = torch.device(device)
            try:
                pipe.to(torch_dev)
            except Exception as e:
                if device_cfg == "auto" and device == "cuda":
                    logger.warning(
                        "pyannote pipeline failed on CUDA (%s); falling back to CPU", e
                    )
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                    device = "cpu"
                    pipe.to(torch.device("cpu"))
                elif device == "cpu" and torch.cuda.is_available():
                    raise RuntimeError(
                        f"Failed to move pyannote pipeline to CPU: {e}. "
                        "Частая причина: задачу обрабатывает diarization-worker-gpu при почти "
                        "полной VRAM — остановите GPU-воркер и используйте только "
                        "diarization-worker (профиль diarization, device: cpu). "
                        "Проверьте: nvidia-smi (свободная память) и "
                        "docker compose ps diarization-worker diarization-worker-gpu."
                    ) from e
                else:
                    raise RuntimeError(
                        f"Failed to move pyannote pipeline to device={device}: {e}"
                    ) from e

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
            for turn, _, speaker in _iter_labeled_turns(diar):
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

