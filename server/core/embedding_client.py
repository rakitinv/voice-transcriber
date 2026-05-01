"""HTTP clients for text embeddings (Ollama / OpenAI-compatible)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from core.config import EmbeddingsConfig
from core.logging import logger


def embed_text_sync(text: str, cfg: EmbeddingsConfig) -> list[float]:
    """Return embedding vector for non-empty text (raises on HTTP/model errors)."""
    t = text.strip()
    if not t:
        raise ValueError("empty text")

    prov = (cfg.provider or "ollama").strip().lower()
    timeout = httpx.Timeout(cfg.timeout_seconds)

    if prov == "openai":
        return _openai_embed(t, cfg, timeout)
    return _ollama_embed(t, cfg, timeout)


def _ollama_embed(text: str, cfg: EmbeddingsConfig, timeout: httpx.Timeout) -> list[float]:
    base = (cfg.base_url or "http://127.0.0.1:11434").rstrip("/")
    url = f"{base}/api/embeddings"
    payload = {"model": cfg.model, "prompt": text}
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
    vec = data.get("embedding")
    if not isinstance(vec, list) or not vec:
        logger.error("Unexpected Ollama embeddings response: %s", json.dumps(data)[:500])
        raise RuntimeError("ollama_embeddings_invalid")
    return [float(x) for x in vec]


def _openai_embed(text: str, cfg: EmbeddingsConfig, timeout: httpx.Timeout) -> list[float]:
    key = (cfg.openai_api_key or "").strip()
    if not key:
        raise RuntimeError("openai_api_key_missing")
    base = (cfg.openai_base_url or "https://api.openai.com/v1").rstrip("/")
    url = f"{base}/embeddings"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {"model": cfg.model, "input": text}
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    arr = data.get("data")
    if not isinstance(arr, list) or not arr:
        raise RuntimeError("openai_embeddings_invalid")
    emb = arr[0].get("embedding") if isinstance(arr[0], dict) else None
    if not isinstance(emb, list) or not emb:
        raise RuntimeError("openai_embeddings_invalid")
    return [float(x) for x in emb]
