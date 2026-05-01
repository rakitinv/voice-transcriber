"""
Декод WebM (Opus) → PCM s16le mono через ffmpeg (stdin/stdout).

Используется для /ws/audio: пороги chunk/window по времени после декодирования.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading

from .logging import logger

DEFAULT_PCM_SAMPLE_RATE = 16_000


def ffmpeg_binary() -> str | None:
    return shutil.which(os.environ.get("VT_FFMPEG_PATH", "ffmpeg"))


class FfmpegWebmPcmPipe:
    """
    Поток: в stdin пишутся фрагменты WebM (как от MediaRecorder), из stdout читается PCM.
    """

    def __init__(self, sample_rate: int = DEFAULT_PCM_SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._ffmpeg = ffmpeg_binary()
        self._proc: subprocess.Popen | None = None
        self._pcm = bytearray()
        self._lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return bool(self._ffmpeg)

    def _start(self) -> None:
        if self._proc is not None:
            return
        if not self._ffmpeg:
            raise RuntimeError("ffmpeg not found on PATH (set VT_FFMPEG_PATH)")

        self._proc = subprocess.Popen(
            [
                self._ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-fflags",
                "+genpts",
                "-f",
                "webm",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                str(self._sample_rate),
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        def read_stdout() -> None:
            assert self._proc and self._proc.stdout
            while True:
                chunk = self._proc.stdout.read(8192)
                if not chunk:
                    break
                with self._lock:
                    self._pcm.extend(chunk)

        self._reader_thread = threading.Thread(target=read_stdout, daemon=True)
        self._reader_thread.start()

    def write_webm(self, data: bytes) -> None:
        if not data:
            return
        self._start()
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(data)
        self._proc.stdin.flush()

    def drain_pcm(self) -> bytes:
        """Забирает весь накопленный PCM с последнего вызова (потокобезопасно)."""
        with self._lock:
            out = bytes(self._pcm)
            self._pcm.clear()
            return out

    def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        stdin = proc.stdin
        if stdin:
            try:
                stdin.close()
            except BrokenPipeError:
                pass
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        self._proc = None


def webm_to_pcm_one_shot(webm_bytes: bytes, sample_rate: int = DEFAULT_PCM_SAMPLE_RATE) -> bytes:
    """
    Декод одного завершённого WebM-блока или файла (удобно для тестов).
    """
    exe = ffmpeg_binary()
    if not exe:
        raise RuntimeError("ffmpeg not found")
    proc = subprocess.run(
        [
            exe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "webm",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "pipe:1",
        ],
        input=webm_bytes,
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")[:500]
        logger.warning("ffmpeg one-shot decode failed: %s", err)
        raise RuntimeError(f"ffmpeg failed: {err}")
    return proc.stdout
