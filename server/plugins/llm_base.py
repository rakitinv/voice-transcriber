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

# Prompt-facing labels for common ISO 639-1 codes (fallback keeps code explicit).
_SUMMARY_LANG_LABELS: Dict[str, str] = {
    "ru": "Russian",
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "uk": "Ukrainian",
    "pt": "Portuguese",
    "zh": "Chinese",
    "ja": "Japanese",
}


def summary_language_prompt_label(iso639_1: str) -> str:
    code = (iso639_1 or "").strip().lower()
    if not code:
        return "Russian"
    return _SUMMARY_LANG_LABELS.get(code, f"ISO 639-1 language code {code}")


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
    def summarize(self, transcript: Dict[str, Any], *, output_language: str | None = None) -> str:
        """
        Generate a summary given a transcript JSON.

        Args:
            transcript: Transcript dictionary with segments

        Returns:
            Summary text (Markdown format)
        """
        raise NotImplementedError

    def summarize_chain_markdown(
        self, markdown_bundle: str, *, output_language: str | None = None
    ) -> str:
        """ТЗ §7.6: сводка по нескольким сегментам цепочки в одном markdown-блоке."""
        text = (markdown_bundle or "").strip()
        if not text:
            return "_Empty transcript._"
        lang = summary_language_prompt_label(output_language or "en")
        wrapped = (
            "Below are chronological transcript segments from one recording session "
            "(possibly split across multiple conversation IDs due to autoprolong). "
            f"Produce a concise Markdown summary entirely in {lang}: main topics, "
            "decisions, action items, and notable speakers when evident. "
            "Do not switch languages.\n\n"
            "---\n\n"
            f"{text}"
        )
        return self.summarize(
            {
                "segments": [
                    {
                        "speaker": "Transcripts",
                        "start": 0.0,
                        "end": 0.0,
                        "text": wrapped,
                    }
                ]
            },
            output_language=output_language,
        )

