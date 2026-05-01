from __future__ import annotations

from typing import Any, Dict, Optional

from core.config import app_config
from plugins.diarization_base import DiarizationProvider


def _provider_class(engine_name: str):
    if engine_name == "pyannote":
        from .pyannote_provider import PyannoteDiarizationProvider

        return PyannoteDiarizationProvider
    return None


def build_diarization_provider(
    engine_name: str, config_override: Optional[Dict[str, Any]] = None
) -> DiarizationProvider:
    engine_name = engine_name.lower().strip()
    provider_cls = _provider_class(engine_name)
    if provider_cls is None:
        raise ValueError(f"Unknown diarization engine: {engine_name}")

    base_cfg = app_config.diarization.providers.get(engine_name)
    cfg_dict: Dict[str, Any] = {}
    if base_cfg is not None:
        cfg_dict = {
            "enabled": base_cfg.enabled,
            "impl": base_cfg.impl,
            "model": base_cfg.model,
            "device": base_cfg.device,
            "hf_token_env": base_cfg.hf_token_env,
            "offline_models": base_cfg.offline_models,
            "model_cache_dir": base_cfg.model_cache_dir,
            "num_speakers": base_cfg.num_speakers,
            "min_speakers": base_cfg.min_speakers,
            "max_speakers": base_cfg.max_speakers,
        }

    if config_override:
        cfg_dict.update(config_override)

    return provider_cls(cfg_dict)

