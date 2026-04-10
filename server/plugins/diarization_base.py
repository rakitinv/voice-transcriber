"""
Base interfaces for diarization providers.

Concrete implementations:
- WhisperX
- Pyannote
- FasterWhisper + Pyannote hybrid
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class DiarizationSegment:
    """Diarization segment with speaker label and timestamps."""

    speaker: str
    start: float
    end: float
    text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {"speaker": self.speaker, "start": self.start, "end": self.end}
        if self.text:
            result["text"] = self.text
        return result


class DiarizationProvider(ABC):
    """Abstract base class for diarization providers."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize provider with configuration."""
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        raise NotImplementedError

    @abstractmethod
    def run(
        self, audio_path: str, transcript_segments: Optional[List[Dict[str, Any]]] = None
    ) -> List[DiarizationSegment]:
        """
        Run diarization and return speaker-labeled segments.

        Args:
            audio_path: Path to audio file
            transcript_segments: Optional pre-computed transcript segments for hybrid approaches

        Returns:
            List of diarization segments with speaker labels
        """
        raise NotImplementedError

