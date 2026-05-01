"""
Публичные лимиты сервера и пользовательские настройки (Phase A).
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.asr.vad_prefs import read_asr_vad_env_defaults
from core.config import app_config
from core.diarization_prefs import effective_turn_level_retranscription
from core.db import get_db
from ..models import User, UserOAuthIdentity
from .dependencies import get_current_user

router = APIRouter(prefix="/settings", tags=["settings"])


class AsrVadDefaultsOut(BaseModel):
    vad_filter: bool
    min_silence_ms: int = Field(ge=50, le=5000)
    threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    speech_pad_ms: Optional[int] = Field(default=None, ge=0, le=5000)


class ServerLimitsResponse(BaseModel):
    """Согласовано с openapi.yaml components/schemas/ServerLimits."""

    max_duration_seconds: int
    max_file_size_bytes: int
    max_ttl_days: int
    allowed_realtime_modes: list[str]
    default_realtime_mode: str
    chunk_ms_min: int
    chunk_ms_max: int
    max_window_ms: int
    autoprolong_enabled: bool
    autoprolong_tail_seconds: float = Field(
        description="Догрузка хвоста в разговор A перед стартом B (секунды)"
    )
    asr_vad_defaults: Optional[AsrVadDefaultsOut] = Field(
        default=None,
        description="Текущие дефолты VAD из окружения сервера (для подсказок в UI)",
    )
    diarization_turn_level_retranscription_default: bool = Field(
        default=False,
        description="Серверный YAML/env: повторный ASR на каждый turn при диаризации",
    )
    llm_session_summary_enabled: bool = Field(
        default=False,
        description="ТЗ §7.6 — rolling LLM summary по цепочке recording_session_id",
    )


class UserSettingsResponse(BaseModel):
    default_language: str = "en"
    default_ttl_days: int = Field(ge=1)
    search_mode: Literal["fulltext", "semantic"] = "fulltext"
    asr_vad_use_custom: bool = False
    asr_vad_filter: bool = True
    asr_vad_min_silence_ms: int = Field(default=500, ge=50, le=5000)
    asr_vad_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    asr_vad_speech_pad_ms: Optional[int] = Field(default=None, ge=0, le=5000)
    diarization_turn_level_retranscription_use_custom: bool = False
    diarization_turn_level_retranscription: bool = Field(
        default=False,
        description="Эффективное значение: повторный ASR по turn при диаризации",
    )


class UserSettingsPatch(BaseModel):
    default_language: Optional[str] = None
    default_ttl_days: Optional[int] = None
    search_mode: Optional[Literal["fulltext", "semantic"]] = None
    asr_vad_use_custom: Optional[bool] = None
    asr_vad_filter: Optional[bool] = None
    asr_vad_min_silence_ms: Optional[int] = None
    asr_vad_threshold: Optional[float] = None
    asr_vad_speech_pad_ms: Optional[int] = None
    diarization_turn_level_retranscription_use_custom: Optional[bool] = None
    diarization_turn_level_retranscription: Optional[bool] = None

    @field_validator("default_ttl_days")
    @classmethod
    def ttl_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("default_ttl_days must be >= 1")
        return v

    @field_validator("asr_vad_min_silence_ms")
    @classmethod
    def vad_min_ms(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (50 <= int(v) <= 5000):
            raise ValueError("asr_vad_min_silence_ms must be between 50 and 5000")
        return v

    @field_validator("asr_vad_threshold")
    @classmethod
    def vad_threshold(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= float(v) <= 1.0):
            raise ValueError("asr_vad_threshold must be between 0.0 and 1.0")
        return v

    @field_validator("asr_vad_speech_pad_ms")
    @classmethod
    def vad_pad_ms(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (0 <= int(v) <= 5000):
            raise ValueError("asr_vad_speech_pad_ms must be between 0 and 5000")
        return v


class OAuthIdentityOut(BaseModel):
    """Привязанный OAuth-субъект (маскированный `sub`) — C7.4."""

    provider: str
    provider_email: Optional[str] = None
    subject_hint: str


def _mask_oauth_subject(sub: str) -> str:
    s = (sub or "").strip()
    if len(s) <= 4:
        return "****"
    return f"…{s[-4:]}"


def _prefs_from_user(user: User) -> dict:
    raw = user.preferences or {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _default_user_settings() -> UserSettingsResponse:
    lim = app_config.limits
    return UserSettingsResponse(
        default_language="en",
        default_ttl_days=min(7, lim.max_ttl_days),
        search_mode="fulltext",
    )


def _user_settings_response(user: User) -> UserSettingsResponse:
    defaults = _default_user_settings()
    p = _prefs_from_user(user)
    lim = app_config.limits
    ttl = int(p.get("default_ttl_days", defaults.default_ttl_days))
    ttl = max(1, min(ttl, lim.max_ttl_days))
    lang = str(p.get("default_language", defaults.default_language))
    mode = p.get("search_mode", defaults.search_mode)
    if mode not in ("fulltext", "semantic"):
        mode = "fulltext"

    env_v = read_asr_vad_env_defaults()
    use_custom = bool(p.get("asr_vad_use_custom", False))
    if use_custom:
        vad_filter = bool(p.get("asr_vad_filter", env_v.vad_filter))
        vad_min = int(p.get("asr_vad_min_silence_ms", env_v.min_silence_ms))
        vad_thr = p.get("asr_vad_threshold", env_v.threshold)
        if vad_thr is not None:
            vad_thr = float(vad_thr)
        vad_pad = p.get("asr_vad_speech_pad_ms", env_v.speech_pad_ms)
        if vad_pad is not None:
            vad_pad = int(vad_pad)
    else:
        vad_filter = env_v.vad_filter
        vad_min = env_v.min_silence_ms
        vad_thr = env_v.threshold
        vad_pad = env_v.speech_pad_ms

    d_use = bool(p.get("diarization_turn_level_retranscription_use_custom", False))
    d_eff = effective_turn_level_retranscription(user)

    return UserSettingsResponse(
        default_language=lang,
        default_ttl_days=ttl,
        search_mode=mode,
        asr_vad_use_custom=use_custom,
        asr_vad_filter=vad_filter,
        asr_vad_min_silence_ms=vad_min,
        asr_vad_threshold=vad_thr,
        asr_vad_speech_pad_ms=vad_pad,
        diarization_turn_level_retranscription_use_custom=d_use,
        diarization_turn_level_retranscription=d_eff,
    )


@router.get("/limits", response_model=ServerLimitsResponse)
async def get_server_limits() -> ServerLimitsResponse:
    """Лимиты и границы realtime для кэширования на клиентах (ТЗ §5)."""
    lim = app_config.limits
    env_v = read_asr_vad_env_defaults()
    vad_out = AsrVadDefaultsOut(
        vad_filter=env_v.vad_filter,
        min_silence_ms=env_v.min_silence_ms,
        threshold=env_v.threshold,
        speech_pad_ms=env_v.speech_pad_ms,
    )
    return ServerLimitsResponse(
        max_duration_seconds=lim.max_duration_seconds,
        max_file_size_bytes=lim.max_file_size_bytes,
        max_ttl_days=lim.max_ttl_days,
        allowed_realtime_modes=list(lim.allowed_realtime_modes),
        default_realtime_mode=lim.default_realtime_mode,
        chunk_ms_min=lim.chunk_ms_min,
        chunk_ms_max=lim.chunk_ms_max,
        max_window_ms=lim.max_window_ms,
        autoprolong_enabled=lim.autoprolong_enabled,
        autoprolong_tail_seconds=lim.autoprolong_tail_seconds,
        asr_vad_defaults=vad_out,
        diarization_turn_level_retranscription_default=app_config.diarization.turn_level_retranscription,
        llm_session_summary_enabled=app_config.llm.session_summary_enabled,
    )


@router.get("/user", response_model=UserSettingsResponse)
async def get_user_settings(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserSettingsResponse:
    return _user_settings_response(current_user)


@router.patch("/user", response_model=UserSettingsResponse)
async def patch_user_settings(
    body: UserSettingsPatch,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserSettingsResponse:
    lim = app_config.limits
    merged = _prefs_from_user(current_user).copy()
    updates = body.model_dump(exclude_unset=True)

    if "default_language" in updates:
        merged["default_language"] = (body.default_language or "").strip() or "en"
    if "default_ttl_days" in updates and body.default_ttl_days is not None:
        ttl = max(1, min(int(body.default_ttl_days), lim.max_ttl_days))
        merged["default_ttl_days"] = ttl
    if "search_mode" in updates and body.search_mode is not None:
        merged["search_mode"] = body.search_mode

    if "asr_vad_use_custom" in updates:
        merged["asr_vad_use_custom"] = bool(body.asr_vad_use_custom)
        if not merged["asr_vad_use_custom"]:
            for k in (
                "asr_vad_filter",
                "asr_vad_min_silence_ms",
                "asr_vad_threshold",
                "asr_vad_speech_pad_ms",
            ):
                merged.pop(k, None)
    if merged.get("asr_vad_use_custom"):
        for k in ("asr_vad_filter", "asr_vad_min_silence_ms", "asr_vad_threshold", "asr_vad_speech_pad_ms"):
            if k not in updates:
                continue
            val = updates[k]
            if k == "asr_vad_filter" and val is not None:
                merged[k] = bool(val)
            elif k == "asr_vad_min_silence_ms" and val is not None:
                merged[k] = int(val)
            elif k == "asr_vad_threshold":
                merged[k] = None if val is None else float(val)
            elif k == "asr_vad_speech_pad_ms":
                merged[k] = None if val is None else int(val)

    if "diarization_turn_level_retranscription_use_custom" in updates:
        merged["diarization_turn_level_retranscription_use_custom"] = bool(
            body.diarization_turn_level_retranscription_use_custom
        )
        if not merged["diarization_turn_level_retranscription_use_custom"]:
            merged.pop("diarization_turn_level_retranscription", None)
    if merged.get("diarization_turn_level_retranscription_use_custom"):
        if (
            "diarization_turn_level_retranscription" in updates
            and body.diarization_turn_level_retranscription is not None
        ):
            merged["diarization_turn_level_retranscription"] = bool(
                body.diarization_turn_level_retranscription
            )

    current_user.preferences = merged
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return _user_settings_response(current_user)


@router.get("/oauth-identities", response_model=list[OAuthIdentityOut])
async def list_oauth_identities(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[OAuthIdentityOut]:
    rows = (
        db.query(UserOAuthIdentity)
        .filter(UserOAuthIdentity.user_id == current_user.id)
        .order_by(UserOAuthIdentity.provider.asc())
        .all()
    )
    return [
        OAuthIdentityOut(
            provider=r.provider,
            provider_email=r.provider_email,
            subject_hint=_mask_oauth_subject(r.provider_subject),
        )
        for r in rows
    ]
