"""
Plugin loader and registry.

Dynamically loads ASR, diarization, and LLM providers from configuration.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Optional, Type

from .asr_base import ASRProvider
from .diarization_base import DiarizationProvider
from .llm_base import LLMProvider

from core.config import app_config
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

    def _load_asr_provider(
        self, name: str, config: Any
    ) -> Optional[ASRProvider]:
        """Load an ASR provider by name."""
        # For now, return None - concrete implementations will be added later
        # This allows the system to work without all providers installed
        logger.warning(f"ASR provider {name} not yet implemented")
        return None

    def _load_llm_provider(
        self, name: str, config: Any
    ) -> Optional[LLMProvider]:
        """Load an LLM provider by name."""
        # For now, return None - concrete implementations will be added later
        logger.warning(f"LLM provider {name} not yet implemented")
        return None

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


# Global registry instance
plugin_registry = PluginRegistry()
