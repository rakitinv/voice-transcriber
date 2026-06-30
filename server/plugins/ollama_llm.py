"""LLM provider: Ollama HTTP `/api/generate`."""

from __future__ import annotations

from typing import Any, Dict

import httpx

from core.logging import logger

from .llm_base import (
    LLMProvider,
    build_speaker_identify_prompt,
    strip_llm_thinking_artifacts,
    summary_language_prompt_label,
    summary_system_prompt,
)


def _ollama_http_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        err = data.get("error")
        if isinstance(err, str) and err.strip():
            return err.strip()
    except Exception:
        pass
    text = (response.text or "").strip()
    return text[:800] if text else "(empty body)"


class OllamaLLMProvider(LLMProvider):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        base = str(config.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
        model = str(config.get("model") or "llama3").strip()
        logger.info("Ollama LLM provider base_url=%s model=%s", base, model)

    @property
    def name(self) -> str:
        return "ollama"

    def summarize(
        self, transcript: Dict[str, Any], *, output_language: str | None = None
    ) -> str:
        lines: list[str] = []
        for seg in transcript.get("segments") or []:
            if not isinstance(seg, dict):
                continue
            sp = str(seg.get("speaker", "Speaker"))
            body = str(seg.get("text", "")).strip()
            lines.append(f"**{sp}**: {body}")
        bundle = "\n\n".join(lines) if lines else "_No transcript._"

        code = (output_language or "ru").strip().lower()
        if code == "ru":
            lang_clause = "Сводка целиком на русском языке. Не используй английский.\n\n"
            prompt = (
                f"{summary_system_prompt(output_language)}\n\n"
                f"{lang_clause}"
                "Фрагмент разговора:\n\n"
                f"{bundle}\n\n"
                "Сводка:"
            )
        else:
            lang_clause = (
                f"Write the summary entirely in {summary_language_prompt_label(code)}. "
                "Do not switch languages.\n\n"
            )
            prompt = (
                f"{summary_system_prompt(output_language)}\n\n"
                f"{lang_clause}"
                "Conversation excerpt:\n\n"
                f"{bundle}\n\n"
                "Summary:"
            )
        return strip_llm_thinking_artifacts(self._generate(prompt))

    def suggest_speaker_names(
        self,
        speaker_excerpts,
        *,
        output_language: str | None = None,
    ) -> str:
        code = (output_language or "ru").strip().lower()
        prompt = build_speaker_identify_prompt(speaker_excerpts, output_language=code)
        return strip_llm_thinking_artifacts(self._generate(prompt))

    def _generate(self, prompt: str) -> str:
        raw_base = self.config.get("base_url") or "http://127.0.0.1:11434"
        base = str(raw_base).strip().rstrip("/")
        model = str(self.config.get("model") or "llama3").strip()
        url = f"{base}/api/generate"
        try:
            with httpx.Client(timeout=600.0) as client:
                r = client.post(
                    url,
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                    },
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            detail = _ollama_http_detail(e.response)
            logger.error(
                "Ollama LLM HTTP %s %s — %s",
                e.response.status_code,
                url,
                detail[:500],
            )
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"Ollama returned 404 for {url}. "
                    "Most often the model name is wrong or not downloaded: on the Ollama host run "
                    f"`ollama list`, then `ollama pull {model}` (or set configs/llm.yaml / VT_OLLAMA_MODEL "
                    "to a tag from that list, e.g. llama3.2:latest). "
                    f"Ollama says: {detail}"
                ) from e
            raise RuntimeError(
                f"Ollama HTTP {e.response.status_code} at {url}: {detail}"
            ) from e
        except httpx.RequestError as e:
            logger.error("Ollama LLM transport failed: %s", e)
            raise RuntimeError(
                f"Cannot reach Ollama at {url} ({e!s}). "
                "If Celery runs in Docker and Ollama on the host, set VT_OLLAMA_BASE_URL "
                "(e.g. http://host.docker.internal:11434). Ensure Ollama is running "
                "and listening on 0.0.0.0:11434 if needed (OLLAMA_HOST)."
            ) from e
        except Exception as e:
            logger.error("Ollama LLM request failed: %s", e)
            raise
        out = str(data.get("response") or "").strip()
        if not out:
            raise RuntimeError("ollama_empty_response")
        return out
