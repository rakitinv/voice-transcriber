"""Server + user preferences for diarization (turn-level re-ASR vs speaker labeling only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.config import app_config

if TYPE_CHECKING:
    from app.models import User


def effective_turn_level_retranscription(user: User | None) -> bool:
    """
    When True: after pyannote turns, re-run ASR on each turn clip (may change wording).
    When False: keep ASR segment text, assign speakers by overlap with diarization turns.
    """
    srv = app_config.diarization.turn_level_retranscription
    if user is None:
        return srv
    prefs = user.preferences if isinstance(user.preferences, dict) else {}
    if bool(prefs.get("diarization_turn_level_retranscription_use_custom")):
        raw = prefs.get("diarization_turn_level_retranscription")
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        if raw is None:
            return srv
        return bool(raw)
    return srv
