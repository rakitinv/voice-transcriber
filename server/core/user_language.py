"""User preference helpers for language (ASR hints vs LLM summary output)."""

from __future__ import annotations


def llm_summary_output_language(preferences: dict | None) -> str:
    """
    ISO 639-1 code for conversation / recording-session summaries.

    Matches ASR hint semantics from upload/websocket: explicit default_language,
    or Russian when the user chose auto-detect (empty / auto / dash).
    """
    prefs = preferences if isinstance(preferences, dict) else {}
    raw = str(prefs.get("default_language", "")).strip().lower()
    if not raw or raw in ("auto", "—", "-"):
        return "ru"
    return raw
