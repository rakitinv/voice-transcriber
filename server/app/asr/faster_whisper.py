"""
Faster-Whisper: то же ядро, что и у `whisper`, отдельное имя в registry.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from plugins.asr_base import ASRProvider, ASRSegment

from .faster_engine import transcribe_bytes_to_text, transcribe_file_to_segments


class FasterWhisperASRProvider(ASRProvider):
    @property
    def name(self) -> str:
        return "faster_whisper"

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        *,
        vad_preferences: Optional[dict] = None,
    ) -> List[ASRSegment]:
        return transcribe_file_to_segments(
            audio_path, self.config, language=language, vad_preferences=vad_preferences
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
            suffix=".webm",
            vad_preferences=vad_preferences,
        )
