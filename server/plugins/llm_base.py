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


def strip_llm_thinking_artifacts(text: str) -> str:
    """Remove Qwen3 / reasoning-model thinking blocks from visible summary output."""
    import re

    s = (text or "").strip()
    if not s:
        return s
    block_re = re.compile(
        r"<\s*(?:think(?:ing)?|redacted_thinking)\s*>.*?</\s*(?:think(?:ing)?|redacted_thinking)\s*>",
        re.IGNORECASE | re.DOTALL,
    )
    heading_re = re.compile(r"^#{1,3}\s+\S", re.MULTILINE)
    for _ in range(4):
        prev = s
        s = block_re.sub("", s).strip()
        lower = s.lower()
        if "" in lower:
            tail = s[lower.index("") + len("") :].lstrip()
            m = heading_re.search(tail)
            s = tail[m.start() :].lstrip() if m else tail
        for open_tag in ("<think>", "<thinking>"):
            ol = open_tag.lower()
            if ol in lower and f"</{open_tag[1:]}" not in lower:
                idx = lower.index(ol)
                tail = s[idx + len(open_tag) :].lstrip()
                m = heading_re.search(tail)
                s = tail[m.start() :].lstrip() if m else ""
        if s == prev:
            break
    return s.strip()


def summary_system_prompt(output_language: str | None) -> str:
    """System message for summarization (language + no chain-of-thought in output)."""
    code = (output_language or "ru").strip().lower()
    label = summary_language_prompt_label(code)
    if code == "ru":
        return (
            "Ты помощник, который пишет краткие сводки разговоров в Markdown на русском языке. "
            "Ответ — только готовая сводка: без рассуждений, без thinking-блоков, без английского текста."
        )
    return (
        f"You write concise Markdown conversation summaries entirely in {label}. "
        "Output only the final summary — no reasoning, thinking blocks, or chain-of-thought."
    )


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
        code = (output_language or "ru").strip().lower()
        if code == "ru":
            wrapped = (
                "Ниже — хронологические фрагменты транскрипта одной сессии записи "
                "(возможны несколько conversation ID из-за автопродления). "
                "Составь краткую Markdown-сводку целиком на русском языке: основные темы, "
                "решения, задачи и спикеры, если видны. Не переключай язык. "
                "Только сводка, без рассуждений.\n\n---\n\n"
                f"{text}"
            )
        else:
            lang = summary_language_prompt_label(code)
            wrapped = (
                "Below are chronological transcript segments from one recording session "
                "(possibly split across multiple conversation IDs due to autoprolong). "
                f"Produce a concise Markdown summary entirely in {lang}: main topics, "
                "decisions, action items, and notable speakers when evident. "
                "Do not switch languages.\n\n---\n\n"
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

