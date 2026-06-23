"""Resolve ASR provider and model for realtime vs final tiers."""

from __future__ import annotations

from typing import Literal

from core.config import ASRConfig

AsrTier = Literal["realtime", "final"]


def resolve_asr_provider_name(cfg: ASRConfig, tier: AsrTier | None = None) -> str:
    """Effective provider name for a tier; falls back to ``default_provider``."""
    if tier == "realtime":
        return (cfg.realtime_provider or cfg.default_provider or "").strip()
    if tier == "final":
        return (cfg.final_provider or cfg.default_provider or "").strip()
    return (cfg.default_provider or "").strip()


def resolve_asr_recognition_model(
    cfg: ASRConfig, provider_name: str, tier: AsrTier | None = None
) -> str | None:
    """
  Tier-specific model override, then legacy ``recognition_model`` for ``default_provider``.
    """
    pname = (provider_name or "").strip().lower()
    default_name = (cfg.default_provider or "").strip().lower()

    if tier == "realtime" and cfg.realtime_recognition_model:
        return str(cfg.realtime_recognition_model).strip() or None
    if tier == "final" and cfg.final_recognition_model:
        return str(cfg.final_recognition_model).strip() or None

    if cfg.recognition_model and pname and pname == default_name:
        return str(cfg.recognition_model).strip() or None
    return None
