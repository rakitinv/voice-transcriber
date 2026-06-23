"""
Read-only effective pipeline configuration for Admin API (ADMIN_OPS_CONSOLE §4.2).

Exposes merged YAML + env overrides from ``app_config`` without secrets or internal URLs
that embed credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.config import app_config


@dataclass(frozen=True)
class _AsrProviderOut:
    name: str
    enabled: bool
    model: str | None
    impl: str | None


@dataclass(frozen=True)
class _AsrOut:
    default_provider: str
    realtime_provider: str | None
    final_provider: str | None
    recognition_model: str | None
    realtime_recognition_model: str | None
    final_recognition_model: str | None
    providers: tuple[_AsrProviderOut, ...]


@dataclass(frozen=True)
class _DiarProviderOut:
    name: str
    enabled: bool
    impl: str | None
    model: str | None
    device: str | None
    hf_token_env: str | None
    offline_models: bool


@dataclass(frozen=True)
class _DiarOut:
    enabled: bool
    default_provider: str | None
    turn_level_retranscription: bool
    providers: tuple[_DiarProviderOut, ...]


@dataclass(frozen=True)
class _LlmProviderOut:
    name: str
    enabled: bool
    base_url: str | None
    model: str | None


@dataclass(frozen=True)
class _LlmOut:
    default_provider: str
    session_summary_enabled: bool
    session_summary_max_input_chars: int
    providers: tuple[_LlmProviderOut, ...]


@dataclass(frozen=True)
class _EmbOut:
    enabled: bool
    provider: str
    model: str
    base_url: str | None
    openai_base_url: str | None
    timeout_seconds: float
    max_input_chars: int


@dataclass(frozen=True)
class _LimitsOut:
    chunk_ms_min: int
    chunk_ms_max: int
    default_realtime_mode: str
    allowed_realtime_modes: tuple[str, ...]
    max_window_ms: int
    autoprolong_enabled: bool
    autoprolong_tail_seconds: float


@dataclass(frozen=True)
class PipelineRuntimeSnapshot:
    environment: str
    asr: _AsrOut
    diarization: _DiarOut
    llm: _LlmOut
    embeddings: _EmbOut
    limits: _LimitsOut


def build_pipeline_runtime_snapshot() -> PipelineRuntimeSnapshot:
    cfg = app_config
    asr_providers: list[_AsrProviderOut] = []
    for name, p in sorted(cfg.asr.providers.items()):
        asr_providers.append(
            _AsrProviderOut(
                name=name,
                enabled=p.enabled,
                model=p.model,
                impl=p.impl,
            )
        )
    diar_providers: list[_DiarProviderOut] = []
    for name, p in sorted(cfg.diarization.providers.items()):
        diar_providers.append(
            _DiarProviderOut(
                name=name,
                enabled=p.enabled,
                impl=p.impl,
                model=p.model,
                device=p.device,
                hf_token_env=p.hf_token_env,
                offline_models=p.offline_models,
            )
        )
    llm_providers: list[_LlmProviderOut] = []
    for name, p in sorted(cfg.llm.providers.items()):
        llm_providers.append(
            _LlmProviderOut(
                name=name,
                enabled=p.enabled,
                base_url=p.base_url,
                model=p.model,
            )
        )
    emb = cfg.embeddings
    lim = cfg.limits
    return PipelineRuntimeSnapshot(
        environment=str(cfg.environment or "").strip() or "unknown",
        asr=_AsrOut(
            default_provider=cfg.asr.default_provider,
            realtime_provider=cfg.asr.realtime_provider,
            final_provider=cfg.asr.final_provider,
            recognition_model=cfg.asr.recognition_model,
            realtime_recognition_model=cfg.asr.realtime_recognition_model,
            final_recognition_model=cfg.asr.final_recognition_model,
            providers=tuple(asr_providers),
        ),
        diarization=_DiarOut(
            enabled=cfg.diarization.enabled,
            default_provider=cfg.diarization.default_provider,
            turn_level_retranscription=cfg.diarization.turn_level_retranscription,
            providers=tuple(diar_providers),
        ),
        llm=_LlmOut(
            default_provider=str(cfg.llm.default_provider or ""),
            session_summary_enabled=cfg.llm.session_summary_enabled,
            session_summary_max_input_chars=cfg.llm.session_summary_max_input_chars,
            providers=tuple(llm_providers),
        ),
        embeddings=_EmbOut(
            enabled=emb.enabled,
            provider=emb.provider,
            model=emb.model,
            base_url=emb.base_url,
            openai_base_url=emb.openai_base_url,
            timeout_seconds=emb.timeout_seconds,
            max_input_chars=emb.max_input_chars,
        ),
        limits=_LimitsOut(
            chunk_ms_min=lim.chunk_ms_min,
            chunk_ms_max=lim.chunk_ms_max,
            default_realtime_mode=lim.default_realtime_mode,
            allowed_realtime_modes=lim.allowed_realtime_modes,
            max_window_ms=lim.max_window_ms,
            autoprolong_enabled=lim.autoprolong_enabled,
            autoprolong_tail_seconds=lim.autoprolong_tail_seconds,
        ),
    )


def snapshot_to_jsonable(snapshot: PipelineRuntimeSnapshot) -> dict[str, Any]:
    """Nested dicts for Pydantic response_model validation."""

    def _asr_provider(x: _AsrProviderOut) -> dict[str, Any]:
        return {
            "name": x.name,
            "enabled": x.enabled,
            "model": x.model,
            "impl": x.impl,
        }

    def _diar_provider(x: _DiarProviderOut) -> dict[str, Any]:
        return {
            "name": x.name,
            "enabled": x.enabled,
            "impl": x.impl,
            "model": x.model,
            "device": x.device,
            "hf_token_env": x.hf_token_env,
            "offline_models": x.offline_models,
        }

    def _llm_provider(x: _LlmProviderOut) -> dict[str, Any]:
        return {
            "name": x.name,
            "enabled": x.enabled,
            "base_url": x.base_url,
            "model": x.model,
        }

    s = snapshot
    return {
        "environment": s.environment,
        "asr": {
            "default_provider": s.asr.default_provider,
            "realtime_provider": s.asr.realtime_provider,
            "final_provider": s.asr.final_provider,
            "recognition_model": s.asr.recognition_model,
            "realtime_recognition_model": s.asr.realtime_recognition_model,
            "final_recognition_model": s.asr.final_recognition_model,
            "providers": [_asr_provider(p) for p in s.asr.providers],
        },
        "diarization": {
            "enabled": s.diarization.enabled,
            "default_provider": s.diarization.default_provider,
            "turn_level_retranscription": s.diarization.turn_level_retranscription,
            "providers": [_diar_provider(p) for p in s.diarization.providers],
        },
        "llm": {
            "default_provider": s.llm.default_provider,
            "session_summary_enabled": s.llm.session_summary_enabled,
            "session_summary_max_input_chars": s.llm.session_summary_max_input_chars,
            "providers": [_llm_provider(p) for p in s.llm.providers],
        },
        "embeddings": {
            "enabled": s.embeddings.enabled,
            "provider": s.embeddings.provider,
            "model": s.embeddings.model,
            "base_url": s.embeddings.base_url,
            "openai_base_url": s.embeddings.openai_base_url,
            "timeout_seconds": s.embeddings.timeout_seconds,
            "max_input_chars": s.embeddings.max_input_chars,
        },
        "limits": {
            "chunk_ms_min": s.limits.chunk_ms_min,
            "chunk_ms_max": s.limits.chunk_ms_max,
            "default_realtime_mode": s.limits.default_realtime_mode,
            "allowed_realtime_modes": list(s.limits.allowed_realtime_modes),
            "max_window_ms": s.limits.max_window_ms,
            "autoprolong_enabled": s.limits.autoprolong_enabled,
            "autoprolong_tail_seconds": s.limits.autoprolong_tail_seconds,
        },
    }
