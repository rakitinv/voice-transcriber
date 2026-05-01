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


def build_asr_provider(
    engine_name: str, config_override: Optional[Dict[str, Any]] = None
) -> ASRProvider:
    """
    Собирает ASRProvider по имени движка.

    Конфиг из `app_config.asr.providers[engine_name]`; `config_override` — доп. поля.
    Для движка, совпадающего с `app_config.asr.default_provider`, поле **model**
    берётся из **`app_config.asr.recognition_model`** (configs/asr.yaml или `VT_ASR_MODEL`),
    если оно задано — так задаётся текущая используемая модель.
    """
    engine_name = engine_name.lower()
    provider_cls = ENGINE_PROVIDER_MAP.get(engine_name)
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
        }

    default_name = (app_config.asr.default_provider or "").lower().strip()
    if default_name and engine_name == default_name and app_config.asr.recognition_model:
        cfg_dict["model"] = app_config.asr.recognition_model

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

