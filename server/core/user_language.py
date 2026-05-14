"""User preference helpers for language (ASR hints vs LLM summary output)."""

from __future__ import annotations


def default_asr_language_hint_from_preferences(preferences: dict | None) -> str | None:
    """
    ASR language hint (ISO 639-1), or None for auto-detect.

    Same rules as ``app.api.upload._default_language_hint`` (keep in sync).
    """
    prefs = preferences if isinstance(preferences, dict) else {}
    raw = str(prefs.get("default_language", "")).strip().lower()
    if not raw or raw in ("auto", "—", "-"):
        return None
    return raw


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
