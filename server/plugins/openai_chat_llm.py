"""LLM provider: OpenAI-compatible ``/v1/chat/completions`` (vLLM, LM Studio, OpenAI)."""

from __future__ import annotations

from typing import Any, Dict

import httpx

from core.logging import logger

from .llm_base import (
    LLMProvider,
    strip_llm_thinking_artifacts,
    summary_language_prompt_label,
    summary_system_prompt,
)


def _http_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        err = data.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
        if isinstance(err, str) and err.strip():
            return err.strip()
    except Exception:
        pass
    text = (response.text or "").strip()
    return text[:800] if text else "(empty body)"


def _disable_thinking_in_payload(payload: Dict[str, Any], config: Dict[str, Any]) -> None:
    """Qwen3 in vLLM enables thinking by default; summaries need final answer only."""
    raw = config.get("disable_thinking")
    if raw is None:
        disable = True
    else:
        disable = str(raw).strip().lower() in ("1", "true", "yes", "on")
    if disable:
        payload["chat_template_kwargs"] = {"enable_thinking": False}


class OpenAIChatLLMProvider(LLMProvider):
    """Chat completions API used by vLLM (``--served-model-name``) and OpenAI."""

    def __init__(self, config: Dict[str, Any], *, provider_name: str = "openai"):
        super().__init__(config)
        self._provider_name = (provider_name or "openai").strip().lower()
        base = str(config.get("base_url") or "http://127.0.0.1:8000/v1").strip().rstrip("/")
        model = str(config.get("model") or "gpt-4o-mini").strip()
        logger.info(
            "%s LLM provider base_url=%s model=%s",
            self._provider_name,
            base,
            model,
        )

    @property
    def name(self) -> str:
        return self._provider_name

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
            lang_clause = (
                "Сводка целиком на русском языке. Не используй английский. "
                "Только итоговая сводка, без рассуждений.\n\n"
            )
            user_prompt = (
                f"{lang_clause}"
                "Фрагмент разговора:\n\n"
                f"{bundle}\n\n"
                "Сводка:"
            )
        else:
            label = summary_language_prompt_label(code)
            lang_clause = (
                f"Write the summary entirely in {label}. Do not switch languages.\n\n"
            )
            user_prompt = (
                f"{lang_clause}"
                "Conversation excerpt:\n\n"
                f"{bundle}\n\n"
                "Summary:"
            )
        return self._chat(system=summary_system_prompt(output_language), user=user_prompt)

    def _chat(self, *, system: str, user: str) -> str:
        raw_base = self.config.get("base_url") or "http://127.0.0.1:8000/v1"
        base = str(raw_base).strip().rstrip("/")
        model = str(self.config.get("model") or "gpt-4o-mini").strip()
        api_key = str(self.config.get("api_key") or "").strip() or "EMPTY"
        url = f"{base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        if self._provider_name == "vllm":
            _disable_thinking_in_payload(payload, self.config)

        try:
            with httpx.Client(timeout=600.0) as client:
                r = client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            detail = _http_detail(e.response)
            logger.error(
                "%s LLM HTTP %s %s — %s",
                self._provider_name,
                e.response.status_code,
                url,
                detail[:500],
            )
            raise RuntimeError(
                f"{self._provider_name} HTTP {e.response.status_code} at {url}: {detail}"
            ) from e
        except httpx.RequestError as e:
            logger.error("%s LLM transport failed: %s", self._provider_name, e)
            raise RuntimeError(
                f"Cannot reach {self._provider_name} at {url} ({e!s}). "
                "From Docker use host IP or host.docker.internal; check vLLM listen address."
            ) from e

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"{self._provider_name}_empty_choices")
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = ""
        if isinstance(msg, dict):
            content = str(msg.get("content") or "").strip()
            if not content:
                content = str(msg.get("reasoning_content") or "").strip()
        content = strip_llm_thinking_artifacts(content)
        if not content:
            raise RuntimeError(f"{self._provider_name}_empty_response")
        return content
