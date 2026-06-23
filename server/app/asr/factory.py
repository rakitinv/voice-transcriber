"""
ASR pipeline factory.

Creates ASRPipeline instances backed by engine-specific providers:
- Whisper
- Faster-Whisper
- Vosk
- GigaAM

Engines and defaults are driven by `configs/asr.yaml` via `core.config.app_config`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

from core.asr_tier import AsrTier, resolve_asr_recognition_model
from core.config import app_config
from plugins.asr_base import ASRProvider

from .base import ASRPipeline, ASRRealtimeConfig

# Known engine names (classes loaded lazily to avoid optional deps at import time).
ENGINE_NAMES = frozenset({"whisper", "faster_whisper", "vosk", "gigaam"})


def _provider_class(engine_name: str) -> Type[ASRProvider] | None:
    engine_name = engine_name.lower().strip()
    if engine_name == "whisper":
        from .whisper import WhisperASRProvider

        return WhisperASRProvider
    if engine_name == "faster_whisper":
        from .faster_whisper import FasterWhisperASRProvider

        return FasterWhisperASRProvider
    if engine_name == "vosk":
        from .vosk import VoskASRProvider

        return VoskASRProvider
    if engine_name == "gigaam":
        from .gigaam import GigaAMASRProvider

        return GigaAMASRProvider
    return None


def build_asr_provider(
    engine_name: str,
    config_override: Optional[Dict[str, Any]] = None,
    *,
    tier: AsrTier | None = None,
) -> ASRProvider:
    """
    Собирает ASRProvider по имени движка.

    Конфиг из `app_config.asr.providers[engine_name]`; `config_override` — доп. поля.
    Модель выбирается через tier (`realtime` / `final`) или legacy ``recognition_model``
    для ``default_provider``.
    """
    engine_name = engine_name.lower()
    provider_cls = _provider_class(engine_name)
    if provider_cls is None:
        raise ValueError(f"Unknown ASR engine: {engine_name}")

    base_cfg = app_config.asr.providers.get(engine_name)
    cfg_dict: Dict[str, Any] = {}
    if base_cfg is not None:
        cfg_dict = {
            "enabled": base_cfg.enabled,
            "model": base_cfg.model,
            "impl": base_cfg.impl,
            "model_path": base_cfg.model_path,
            "longform_enabled": base_cfg.longform_enabled,
            "hf_token_env": base_cfg.hf_token_env,
            "model_cache_dir": base_cfg.model_cache_dir,
        }

    model_ov = resolve_asr_recognition_model(app_config.asr, engine_name, tier)
    if model_ov:
        cfg_dict["model"] = model_ov

    if config_override:
        cfg_dict.update(config_override)

    return provider_cls(cfg_dict)


def _build_provider(
    engine_name: str, config_override: Optional[Dict[str, Any]] = None
) -> ASRProvider:
    """Обратная совместимость; предпочтительно `build_asr_provider`."""
    return build_asr_provider(engine_name, config_override=config_override)


def create_asr_pipeline(
    engine_name: Optional[str] = None,
    realtime_config: Optional[ASRRealtimeConfig] = None,
    provider_config_override: Optional[Dict[str, Any]] = None,
) -> ASRPipeline:
    """
    Create an ASRPipeline for the requested engine.

    Args:
        engine_name: Name of the ASR engine (whisper, faster_whisper, vosk, gigaam). If None,
            uses `app_config.asr.default_provider`.
        realtime_config: Optional ASRRealtimeConfig; if None, defaults are used.
        provider_config_override: Optional extra configuration dict to merge into the
            provider-specific configuration from YAML.

    Returns:
        Configured ASRPipeline instance.
    """
    if engine_name is None:
        from core.asr_tier import resolve_asr_provider_name

        engine_name = resolve_asr_provider_name(app_config.asr, "realtime")

    provider = _build_provider(engine_name, config_override=provider_config_override)
    return ASRPipeline(provider=provider, realtime_config=realtime_config)
