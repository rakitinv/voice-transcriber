"""
Faster-Whisper-based ASR provider stub.

This module provides a concrete ASRProvider implementation wrapping a
Faster-Whisper backend. Heavy model / runtime specifics are left to be
implemented later.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from plugins.asr_base import ASRProvider, ASRSegment


class FasterWhisperASRProvider(ASRProvider):
    """ASRProvider implementation backed by Faster-Whisper (stub)."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # TODO: Initialize Faster-Whisper model from config

    @property
    def name(self) -> str:
        return "faster_whisper"

    def transcribe(
        self, audio_path: str, language: Optional[str] = None
    ) -> List[ASRSegment]:
        """
        Transcribe an audio file using Faster-Whisper.

        NOTE:
            Stub implementation; extend with real inference code.
        """
        raise NotImplementedError(
            "FasterWhisperASRProvider.transcribe is not implemented yet"
        )

    def transcribe_chunk(self, audio_data: bytes, language: Optional[str] = None) -> str:
        """
        Transcribe a small audio chunk using Faster-Whisper.

        NOTE:
            Stub implementation; extend with buffering/streaming logic as needed.
        """
        raise NotImplementedError(
            "FasterWhisperASRProvider.transcribe_chunk is not implemented yet"
        )

