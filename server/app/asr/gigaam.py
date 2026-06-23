"""
GigaAM ASR provider (Russian speech).
"""

from __future__ import annotations

from typing import List, Optional

from plugins.asr_base import ASRProvider, ASRSegment

from .gigaam_engine import transcribe_bytes_to_text, transcribe_file_to_segments


class GigaAMASRProvider(ASRProvider):
    @property
    def name(self) -> str:
        return "gigaam"

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        *,
        vad_preferences: Optional[dict] = None,
    ) -> List[ASRSegment]:
        return transcribe_file_to_segments(
            audio_path,
            self.config,
            language=language,
            vad_preferences=vad_preferences,
        )

    def transcribe_chunk(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
        *,
        vad_preferences: Optional[dict] = None,
    ) -> str:
        return transcribe_bytes_to_text(
            audio_data,
            self.config,
            language=language,
            suffix=".wav",
            vad_preferences=vad_preferences,
        )
