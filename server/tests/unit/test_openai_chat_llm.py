"""Unit tests for OpenAI-compatible LLM provider (vLLM)."""

from __future__ import annotations

import pytest

from plugins.openai_chat_llm import OpenAIChatLLMProvider


def test_vllm_provider_name() -> None:
    p = OpenAIChatLLMProvider({"base_url": "http://127.0.0.1:8000/v1", "model": "m"}, provider_name="vllm")
    assert p.name == "vllm"


def test_apply_llm_env_vllm(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import load_app_config

    load_app_config.cache_clear()
    monkeypatch.setenv("VT_LLM_DEFAULT_PROVIDER", "vllm")
    monkeypatch.setenv("VT_VLLM_BASE_URL", "http://172.17.0.1:9001/v1")
    monkeypatch.setenv("VT_VLLM_MODEL", "Qwen/Qwen3-14B-AWQ")
    cfg = load_app_config()
    assert cfg.llm.default_provider == "vllm"
    vllm = cfg.llm.providers.get("vllm")
    assert vllm is not None
    assert vllm.base_url == "http://172.17.0.1:9001/v1"
    assert vllm.model == "Qwen/Qwen3-14B-AWQ"
    load_app_config.cache_clear()
