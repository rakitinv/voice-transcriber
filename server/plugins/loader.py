"""
Plugin loader and registry.

Dynamically loads ASR, diarization, and LLM providers from configuration.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any, Dict, Optional

from .asr_base import ASRProvider
from .diarization_base import DiarizationProvider
from .llm_base import LLMProvider

from core.config import LLMProviderConfig, app_config
from core.logging import logger


class PluginRegistry:
    """Registry for loaded plugins."""

    def __init__(self):
        self._asr_providers: Dict[str, ASRProvider] = {}
        self._diarization_providers: Dict[str, DiarizationProvider] = {}
        self._llm_providers: Dict[str, LLMProvider] = {}
        self._load_providers()

    def _load_providers(self) -> None:
        """Load all enabled providers from configuration."""
        # Load ASR providers
        for name, provider_cfg in app_config.asr.providers.items():
            if provider_cfg.enabled:
                try:
                    provider = self._load_asr_provider(name, provider_cfg)
                    if provider:
                        self._asr_providers[name] = provider
                        logger.info(f"Loaded ASR provider: {name}")
                except Exception as e:
                    logger.error(f"Failed to load ASR provider {name}: {e}")

        dp = (app_config.asr.default_provider or "").strip()
        if dp and dp in self._asr_providers:
            pcfg = app_config.asr.providers.get(dp)
            eff = app_config.asr.recognition_model or (pcfg.model if pcfg else None)
            logger.info("ASR active: default_provider=%s recognition_model=%s", dp, eff)
        elif dp:
            logger.warning(
                "ASR default_provider=%s not loaded — tasks fall back to stub",
                dp,
            )

        # Load LLM providers
        for name, provider_cfg in app_config.llm.providers.items():
            if provider_cfg.enabled:
                try:
                    provider = self._load_llm_provider(name, provider_cfg)
                    if provider:
                        self._llm_providers[name] = provider
                        logger.info(f"Loaded LLM provider: {name}")
                except Exception as e:
                    logger.error(f"Failed to load LLM provider {name}: {e}")

        # Load diarization providers
        #
        # Heavy stacks (torch/pyannote) must not be imported in API / generic worker images.
        # We therefore only eagerly load diarization providers in processes that explicitly opt in
        # (diarization Celery worker / warmup tooling), while still allowing `diarization.enabled`
        # to control *auto-queueing* after ASR (see workers/tasks/asr.py).
        eager = os.environ.get("VT_EAGER_LOAD_DIARIZATION_PROVIDERS", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        celery_diarization = os.environ.get("VT_CELERY_ENABLE_DIARIZATION", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if not (eager or celery_diarization):
            logger.info(
                "Skipping eager diarization provider load "
                "(set VT_CELERY_ENABLE_DIARIZATION=1 for diarization worker, "
                "or VT_EAGER_LOAD_DIARIZATION_PROVIDERS=1 for local tooling)"
            )
        else:
            for name, provider_cfg in app_config.diarization.providers.items():
                if provider_cfg.enabled:
                    try:
                        provider = self._load_diarization_provider(name, provider_cfg)
                        if provider:
                            self._diarization_providers[name] = provider
                            logger.info(f"Loaded diarization provider: {name}")
                    except Exception as e:
                        logger.error(f"Failed to load diarization provider {name}: {e}")

    def _load_asr_provider(
        self, name: str, config: Any
    ) -> Optional[ASRProvider]:
        """Создаёт провайдер через `app.asr.factory.build_asr_provider` (ADR 0001 / B1.5)."""
        from app.asr.factory import build_asr_provider

        return build_asr_provider(name)

    def _load_llm_provider(
        self, name: str, config: Any
    ) -> Optional[LLMProvider]:
        """Load an LLM provider by name."""
        cfg_dict: Dict[str, Any]
        if isinstance(config, LLMProviderConfig):
            cfg_dict = {k: v for k, v in asdict(config).items() if v is not None}
        elif isinstance(config, dict):
            cfg_dict = dict(config)
        else:
            cfg_dict = {}
        key = (name or "").strip().lower()
        if key == "ollama":
            from .ollama_llm import OllamaLLMProvider

            return OllamaLLMProvider(cfg_dict)
        logger.warning("LLM provider %r has no implementation in this build", name)
        return None

    def _load_diarization_provider(
        self, name: str, config: Any
    ) -> Optional[DiarizationProvider]:
        """Создаёт провайдер через `app.diarization.factory.build_diarization_provider`."""
        from app.diarization.factory import build_diarization_provider

        return build_diarization_provider(name)

    def get_asr_provider(self, name: Optional[str] = None) -> Optional[ASRProvider]:
        """Get an ASR provider by name, or default if None."""
        if name is None:
            name = app_config.asr.default_provider
        return self._asr_providers.get(name)

    def get_llm_provider(self, name: Optional[str] = None) -> Optional[LLMProvider]:
        """Get an LLM provider by name, or default if None."""
        if name is None:
            name = app_config.llm.default_provider
        return self._llm_providers.get(name)

    def get_diarization_provider(
        self, name: Optional[str] = None
    ) -> Optional[DiarizationProvider]:
        """Get a diarization provider by name, or default if None."""
        if name is None:
            name = app_config.diarization.default_provider
        if not name:
            return None
        return self._diarization_providers.get(name)


# Global registry instance
plugin_registry = PluginRegistry()
