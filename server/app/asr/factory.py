"""
ASR pipeline factory.

Creates ASRPipeline instances backed by engine-specific providers:
- Whisper
- Faster-Whisper
- Vosk

Engines and defaults are driven by `configs/asr.yaml` via `core.config.app_config`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.config import app_config
from plugins.asr_base import ASRProvider

from .base import ASRPipeline, ASRRealtimeConfig
from .faster_whisper import FasterWhisperASRProvider
from .vosk import VoskASRProvider
from .whisper import WhisperASRProvider


ENGINE_PROVIDER_MAP = {
    "whisper": WhisperASRProvider,
    "faster_whisper": FasterWhisperASRProvider,
    "vosk": VoskASRProvider,
}


def _build_provider(engine_name: str, config_override: Optional[Dict[str, Any]] = None) -> ASRProvider:
    """
    Build an ASRProvider for the given engine name.

    Configuration is taken from `app_config.asr.providers[engine_name]` and
    optionally overridden by `config_override`.
    """
    engine_name = engine_name.lower()
    provider_cls = ENGINE_PROVIDER_MAP.get(engine_name)
    if provider_cls is None:
        raise ValueError(f"Unknown ASR engine: {engine_name}")

    base_cfg = app_config.asr.providers.get(engine_name)
    cfg_dict: Dict[str, Any] = {}
    if base_cfg is not None:
        # Convert dataclass to dict
        cfg_dict = {
            "enabled": base_cfg.enabled,
            "model": base_cfg.model,
            "impl": base_cfg.impl,
        }

    if config_override:
        cfg_dict.update(config_override)

    return provider_cls(cfg_dict)


def create_asr_pipeline(
    engine_name: Optional[str] = None,
    realtime_config: Optional[ASRRealtimeConfig] = None,
    provider_config_override: Optional[Dict[str, Any]] = None,
) -> ASRPipeline:
    """
    Create an ASRPipeline for the requested engine.

    Args:
        engine_name: Name of the ASR engine (whisper, faster_whisper, vosk). If None,
            uses `app_config.asr.default_provider`.
        realtime_config: Optional ASRRealtimeConfig; if None, defaults are used.
        provider_config_override: Optional extra configuration dict to merge into the
            provider-specific configuration from YAML.

    Returns:
        Configured ASRPipeline instance.
    """
    if engine_name is None:
        engine_name = app_config.asr.default_provider

    provider = _build_provider(engine_name, config_override=provider_config_override)
    return ASRPipeline(provider=provider, realtime_config=realtime_config)

