"""
Base interfaces for LLM providers.

Concrete implementations will include:
- Ollama
- LM Studio
- llama.cpp
- vLLM
- OpenAI
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize provider with configuration."""
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        raise NotImplementedError

    @abstractmethod
    def summarize(self, transcript: Dict[str, Any]) -> str:
        """
        Generate a summary given a transcript JSON.

        Args:
            transcript: Transcript dictionary with segments

        Returns:
            Summary text (Markdown format)
        """
        raise NotImplementedError

