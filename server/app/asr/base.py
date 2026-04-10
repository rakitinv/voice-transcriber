"""
ASR pipeline base types and helpers.

This module defines:
- configuration for realtime transcription modes
- utilities to normalize provider output into the canonical transcript format
- a high-level ASRPipeline that wraps a low-level ASRProvider

The low-level provider interface is defined in `plugins.asr_base.ASRProvider`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from plugins.asr_base import ASRProvider, ASRSegment


class RealtimeMode(str, Enum):
    """Realtime transcription mode."""

    CHUNK = "chunk"  # Mode 1: chunk -> ASR -> partial transcript
    WINDOWED = "windowed"  # Mode 2: window buffer -> ASR -> transcript


@dataclass
class ASRRealtimeConfig:
    """
    Configuration for realtime ASR.

    Attributes:
        chunk_ms: Target chunk size in milliseconds (e.g. 500–2000).
        window_ms: Window size in milliseconds for windowed mode.
        mode: RealtimeMode.CHUNK or RealtimeMode.WINDOWED.
        language: Optional ISO 639-1 language code, None for auto-detect.
    """

    chunk_ms: int = 1000
    window_ms: int = 2000
    mode: RealtimeMode = RealtimeMode.CHUNK
    language: Optional[str] = None


def segments_to_transcript(
    segments: List[ASRSegment], default_speaker: str = "Speaker 1"
) -> Dict[str, Any]:
    """
    Convert a list of ASRSegment objects into the canonical transcript JSON.

    Output format:
    {
      "segments": [
        {
          "speaker": "Speaker 1",
          "start": 10.2,
          "end": 12.4,
          "text": "Hello"
        }
      ]
    }
    """

    result_segments: List[Dict[str, Any]] = []
    for seg in segments:
        seg_dict = seg.to_dict()
        result_segments.append(
            {
                "speaker": seg_dict.get("speaker", default_speaker),
                "start": float(seg_dict.get("start", 0.0)),
                "end": float(seg_dict.get("end", 0.0)),
                "text": seg_dict.get("text", ""),
            }
        )

    return {"segments": result_segments}


class ASRPipeline:
    """
    High-level ASR pipeline that wraps a low-level ASRProvider.

    Responsibilities:
    - provide a simple `transcribe_file` API
    - provide a `transcribe_stream` API for realtime chunked or windowed transcription
    - normalize output into the canonical transcript JSON format

    NOTE:
        Multi-thread splitting of very long audio and advanced buffering/decoding
        are intentionally kept minimal here; the concrete provider implementations
        (Whisper / Faster-Whisper / Vosk) can override or extend this logic.
    """

    def __init__(self, provider: ASRProvider, realtime_config: Optional[ASRRealtimeConfig] = None):
        self.provider = provider
        self.realtime_config = realtime_config or ASRRealtimeConfig()

        # Internal buffer for WINDOWED mode (simplified; counts chunks instead of real time)
        self._window_chunks: List[bytes] = []

    @property
    def name(self) -> str:
        """Name of the underlying provider."""
        return self.provider.name

    # -------- Batch / file transcription --------

    def transcribe_file(self, file_path: str) -> Dict[str, Any]:
        """
        Transcribe a complete audio file.

        For now this is a thin wrapper around the provider's `transcribe` method,
        with output normalized into the canonical transcript format.
        """
        segments = self.provider.transcribe(file_path, language=self.realtime_config.language)
        return segments_to_transcript(segments)

    # -------- Realtime transcription --------

    def transcribe_stream(self, audio_chunk: bytes) -> Dict[str, Any]:
        """
        Transcribe an incoming audio chunk according to the configured realtime mode.

        Mode 1 (CHUNK):
            - each chunk is sent to the provider immediately
            - returns a partial transcript covering that chunk

        Mode 2 (WINDOWED):
            - chunks are accumulated in a simple buffer
            - when enough chunks have been collected for a "window", they are
              concatenated and sent to the provider
            - returns a transcript for the window

        NOTE:
            This implementation uses a very lightweight buffering strategy that does
            not depend on actual audio duration; concrete providers can override
            this method to use proper audio decoding and timing if needed.
        """
        if self.realtime_config.mode == RealtimeMode.CHUNK:
            return self._transcribe_chunk_mode(audio_chunk)
        return self._transcribe_windowed_mode(audio_chunk)

    def _transcribe_chunk_mode(self, audio_chunk: bytes) -> Dict[str, Any]:
        """Mode 1: directly transcribe the given chunk."""
        text = self.provider.transcribe_chunk(audio_chunk, language=self.realtime_config.language)
        # In chunk mode, timestamps are not known; use 0.0 and let caller align if needed.
        seg = ASRSegment(start=0.0, end=0.0, text=text)
        return segments_to_transcript([seg])

    def _transcribe_windowed_mode(self, audio_chunk: bytes) -> Dict[str, Any]:
        """
        Mode 2: accumulate chunks into a simple buffer and transcribe when a window is "full".

        The notion of "full" is simplified: we approximate the desired window size by
        the number of chunks instead of decoding and measuring exact duration.
        """
        self._window_chunks.append(audio_chunk)

        # Heuristic: assume each chunk ~ chunk_ms; compute required chunk count for one window.
        chunks_per_window = max(
            1, int(self.realtime_config.window_ms / max(self.realtime_config.chunk_ms, 1))
        )

        if len(self._window_chunks) < chunks_per_window:
            # Not enough data yet; return empty transcript.
            return {"segments": []}

        # Concatenate buffered chunks and clear buffer.
        window_bytes = b"".join(self._window_chunks)
        self._window_chunks.clear()

        text = self.provider.transcribe_chunk(window_bytes, language=self.realtime_config.language)
        seg = ASRSegment(start=0.0, end=0.0, text=text)
        return segments_to_transcript([seg])

