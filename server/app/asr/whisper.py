"""
Whisper-based ASR provider stub.

This module provides a concrete ASRProvider implementation wrapping a Whisper
backend. The heavy lifting (model loading, audio decoding) is intentionally
left unimplemented here; this stub focuses on wiring and interface shape.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from plugins.asr_base import ASRProvider, ASRSegment


class WhisperASRProvider(ASRProvider):
    """ASRProvider implementation backed by Whisper (stub)."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # TODO: Load Whisper model based on config["model"]

    @property
    def name(self) -> str:
        return "whisper"

    def transcribe(
        self, audio_path: str, language: Optional[str] = None
    ) -> List[ASRSegment]:
        """
        Transcribe an audio file using Whisper.

        NOTE:
            This is a stub implementation; it must be extended with real
            Whisper inference code (e.g. via openai/whisper or faster-whisper).
        """
        raise NotImplementedError("WhisperASRProvider.transcribe is not implemented yet")

    def transcribe_chunk(self, audio_data: bytes, language: Optional[str] = None) -> str:
        """
        Transcribe a small audio chunk using Whisper.

        NOTE:
            This is a stub implementation; it must be extended with real
            streaming / chunk handling logic.
        """
        raise NotImplementedError("WhisperASRProvider.transcribe_chunk is not implemented yet")

