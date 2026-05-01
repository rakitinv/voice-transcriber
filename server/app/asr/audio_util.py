"""Конвертация медиа в WAV 16 kHz mono для Vosk / единообразного ввода."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from core.webm_pcm import ffmpeg_binary


def media_to_wav_16k_mono(src: Path | str) -> Path:
    """
    Создаёт временный `.wav` 16 kHz mono. Вызывающий код должен удалить файл после использования.
    """
    exe = ffmpeg_binary()
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH (set VT_FFMPEG_PATH)")

    src_p = Path(src)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    out = Path(tmp.name)
    try:
        subprocess.run(
            [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(src_p),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                str(out),
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
    except Exception:
        if out.exists():
            out.unlink(missing_ok=True)
        raise
    return out


def bytes_to_tempfile(data: bytes, suffix: str) -> Path:
    t = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        t.write(data)
        t.flush()
        return Path(t.name)
    finally:
        t.close()
