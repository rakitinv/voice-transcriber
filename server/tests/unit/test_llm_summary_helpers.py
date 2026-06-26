"""Tests for LLM summary helpers (language, Qwen3 thinking strip)."""

from __future__ import annotations

from plugins.llm_base import strip_llm_thinking_artifacts, summary_system_prompt


def test_summary_system_prompt_russian() -> None:
    assert "русском" in summary_system_prompt("ru").lower()


def test_strip_thinking_redacted_block() -> None:
    raw = (
        "<think>\nOkay, I need to create a summary in English...\n"
        "</think>\n\n"
        "## Сводка\n\n- Пациент в коме."
    )
    out = strip_llm_thinking_artifacts(raw)
    assert "Okay, I need" not in out
    assert "Сводка" in out


def test_strip_thinking_after_think_close() -> None:
    raw = "reasoning here\n\n## Summary\nRussian text."
    out = strip_llm_thinking_artifacts(raw)
    assert out.startswith("## Summary")
