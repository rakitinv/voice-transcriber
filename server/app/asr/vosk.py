"""
Vosk-based ASR provider stub.

This module provides a concrete ASRProvider implementation wrapping a
Vosk backend. Engine-specific logic is intentionally omitted.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from plugins.asr_base import ASRProvider, ASRSegment


class VoskASRProvider(ASRProvider):
    """ASRProvider implementation backed by Vosk (stub)."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # TODO: Initialize Vosk model / recognizer from config

    @property
    def name(self) -> str:
        return "vosk"

    def transcribe(
        self, audio_path: str, language: Optional[str] = None
    ) -> List[ASRSegment]:
        """
        Transcribe an audio file using Vosk.

        NOTE:
            Stub implementation; extend with actual Vosk recognition pipeline.
        """
        raise NotImplementedError("VoskASRProvider.transcribe is not implemented yet")

    def transcribe_chunk(self, audio_data: bytes, language: Optional[str] = None) -> str:
        """
        Transcribe a small audio chunk using Vosk.

        NOTE:
            Stub implementation; extend with streaming recognition if desired.
        """
        raise NotImplementedError("VoskASRProvider.transcribe_chunk is not implemented yet")

