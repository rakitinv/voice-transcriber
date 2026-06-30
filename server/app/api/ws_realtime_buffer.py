"""
Буфер realtime-аудио: режимы chunk и windowed (см. ТЗ §4, configs/limits.yaml).

- **PCM** (после WebM→PCM): пороги по времени через `pcm_sample_rate` и s16 mono (2 байта/сэмпл).
- **Legacy** (без декодера): оценка сжатого потока `bytes_per_second` для порога по байтам.
"""

from __future__ import annotations

from dataclasses import dataclass

# Оценка «типичного» сжатого голосового потока (байт/с); только для legacy-режима.
_DEFAULT_CONTAINER_BYTES_PER_SECOND = 16_000


@dataclass
class RealtimeBufferParams:
    mode: str  # chunk | windowed
    chunk_ms: int
    max_window_ms: int
    overlap_ms: int = 0
    # Если задан (напр. 16000 после ffmpeg), шаги считаются в PCM s16 mono.
    pcm_sample_rate: int | None = None
    # Если pcm_sample_rate is None — оценка по сырому контейнеру (байт/с).
    bytes_per_second: float = _DEFAULT_CONTAINER_BYTES_PER_SECOND


class RealtimeAudioBuffer:
    """
    Накапливает байты; при достижении шага chunk_ms отдаёт срезы для ASR.

    - chunk: каждый срез — последовательные блоки длиной step_bytes.
    - windowed: каждый срез — последние window_bytes буфера (скользящее окно),
      затем сдвиг на step_bytes с начала буфера.
    """

    def __init__(self, params: RealtimeBufferParams):
        self._p = params
        self._buf = bytearray()
        if params.pcm_sample_rate is not None:
            bps = float(params.pcm_sample_rate * 2)
        else:
            bps = float(params.bytes_per_second)
        self._step_b = max(256, int(params.chunk_ms / 1000.0 * bps))
        self._win_b = max(self._step_b, int(params.max_window_ms / 1000.0 * bps))
        overlap_b = (
            max(0, int(params.overlap_ms / 1000.0 * bps)) if params.overlap_ms > 0 else 0
        )
        self._advance_b = max(256, self._step_b - overlap_b)
        # Защита от неограниченного роста при отсутствии флаша
        self._cap = self._win_b * 8

    def feed(self, data: bytes) -> list[bytes]:
        if not data:
            return []
        self._buf.extend(data)
        if len(self._buf) > self._cap:
            del self._buf[: len(self._buf) - self._cap]

        out: list[bytes] = []
        if self._p.mode == "windowed":
            while len(self._buf) >= self._step_b:
                window = bytes(self._buf[-self._win_b :]) if len(self._buf) > self._win_b else bytes(self._buf)
                out.append(window)
                del self._buf[: self._advance_b]
        else:
            while len(self._buf) >= self._step_b:
                chunk = bytes(self._buf[: self._step_b])
                del self._buf[: self._step_b]
                out.append(chunk)
        return out


def clamp_chunk_ms(raw: int | None, chunk_min: int, chunk_max: int) -> int:
    mid = (chunk_min + chunk_max) // 2
    if raw is None:
        return mid
    return max(chunk_min, min(chunk_max, int(raw)))


def resolve_realtime_mode(
    client_mode: str | None,
    allowed: tuple[str, ...],
    default: str,
) -> str:
    m = (client_mode or "").strip().lower()
    if m in allowed:
        return m
    d = default.lower()
    return d if d in allowed else allowed[0]
