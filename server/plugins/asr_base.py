"""
Base interfaces for ASR providers.

Concrete implementations will wrap:
- Whisper
- Faster-Whisper
- Vosk
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ASRSegment:
    """ASR segment with timestamp and text."""

    start: float
    end: float
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {"start": self.start, "end": self.end, "text": self.text}
        if self.language:
            result["language"] = self.language
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result


class ASRProvider(ABC):
    """Abstract base class for ASR providers."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize provider with configuration."""
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        raise NotImplementedError

    @abstractmethod
    def transcribe(
        self, audio_path: str, language: Optional[str] = None
    ) -> List[ASRSegment]:
        """
        Transcribe an audio file and return segments.

        Args:
            audio_path: Path to audio file
            language: Optional language code (ISO 639-1), None for auto-detect

        Returns:
            List of transcription segments
        """
        raise NotImplementedError

    @abstractmethod
    def transcribe_chunk(self, audio_data: bytes, language: Optional[str] = None) -> str:
        """
        Transcribe a small audio chunk (for realtime mode).

        Args:
            audio_data: Raw audio bytes
            language: Optional language code

        Returns:
            Transcribed text
        """
        raise NotImplementedError

