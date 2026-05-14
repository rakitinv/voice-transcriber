"""
Configuration models and loading.

Configuration is primarily sourced from YAML files in the top-level `configs/`
directory:

- server.yaml
- asr.yaml
- llm.yaml
- limits.yaml
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml


BASE_DIR = Path(__file__).resolve().parents[1]  # .../server
CONFIG_DIR = BASE_DIR.parent / "configs"


@dataclass
class DatabaseConfig:
    url: str


@dataclass
class RedisConfig:
    url: str


@dataclass
class S3Config:
    endpoint: str
    bucket: str
    access_key: str
    secret_key: str


@dataclass
class OAuthProviderConfig:
    client_id: str
    client_secret: str


@dataclass
class AuthLockoutConfig:
    """IP-scoped throttling after failed refresh / API key checks (Redis; ADMIN_OPS sprint 6)."""

    enabled: bool = True
    refresh_invalid_max_per_ip: int = 40
    api_key_invalid_max_per_ip: int = 80
    window_seconds: int = 900
    block_seconds: int = 900


@dataclass
class AuthLoginAuditConfig:
    """Persist auth_signin_events; optional hashed client fingerprint (VT_AUTH_AUDIT_SALT)."""

    enabled: bool = True
    include_client_fingerprint: bool = True
    # Rows older than this are deleted by workers.tasks.cleanup.old_auth_signin_events
    # and workers.tasks.cleanup.old_pipeline_events (0 = never auto-delete for both).
    retention_days: int = 90


@dataclass
class AuthConfig:
    """Loaded from configs/server.yaml (auth.google / auth.yandex), not from Python defaults."""

    google: OAuthProviderConfig
    yandex: OAuthProviderConfig
    lockout: AuthLockoutConfig = field(default_factory=AuthLockoutConfig)
    login_audit: AuthLoginAuditConfig = field(default_factory=AuthLoginAuditConfig)

@dataclass
class LimitsConfig:
    max_duration_seconds: int
    max_file_size_bytes: int
    max_ttl_days: int
    allowed_realtime_modes: Tuple[str, ...]
    default_realtime_mode: str
    chunk_ms_min: int
    chunk_ms_max: int
    max_window_ms: int
    autoprolong_enabled: bool
    autoprolong_tail_seconds: float


@dataclass
class ASRProviderConfig:
    enabled: bool
    model: str | None = None
    impl: str | None = None  # dotted path to implementation, optional
    model_path: str | None = None  # каталог модели (напр. Vosk), см. configs/asr.yaml


@dataclass
class LLMProviderConfig:
    enabled: bool
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


@dataclass
class DiarizationProviderConfig:
    enabled: bool
    impl: str | None = None  # dotted path to implementation, optional
    model: str | None = None
    device: str | None = None  # cpu|cuda|auto
    hf_token_env: str | None = None
    offline_models: bool = False
    model_cache_dir: str | None = None
    num_speakers: int | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None


@dataclass
class DiarizationConfig:
    enabled: bool
    default_provider: str | None
    providers: Dict[str, DiarizationProviderConfig]
    # True: re-ASR each diarization turn clip; False: keep ASR wording, assign speakers by overlap.
    turn_level_retranscription: bool = False


@dataclass
class ASRConfig:
    default_provider: str
    """Имя провайдера из `providers` (whisper / faster_whisper / vosk / …)."""

    recognition_model: str | None
    """Текущая используемая модель для `default_provider` (перекрывает model у записи провайдера)."""

    providers: Dict[str, ASRProviderConfig]


@dataclass
class LLMConfig:
    default_provider: str
    providers: Dict[str, LLMProviderConfig]
    # ТЗ §7.6: один rolling-summary на всю цепочку (recording_session_id).
    session_summary_enabled: bool = False
    session_summary_max_input_chars: int = 120_000


@dataclass
class EmbeddingsConfig:
    """Semantic search indexing (configs/embeddings.yaml)."""

    enabled: bool
    provider: str
    model: str
    base_url: str | None
    openai_base_url: str | None
    openai_api_key: str | None
    timeout_seconds: float
    max_input_chars: int


@dataclass(frozen=True)
class ExternalToolLink:
    """Named URL for Grafana, Flower, MinIO console, etc. (ADMIN_OPS_CONSOLE §4.1)."""

    name: str
    url: str


@dataclass(frozen=True)
class AdminConsoleConfig:
    """Admin / Ops console: external tools and optional product deep-links."""

    external_tools: Tuple[ExternalToolLink, ...] = ()
    product_conversation_url_template: str | None = None


@dataclass
class ServerConfig:
    environment: str
    host: str
    port: int
    database: DatabaseConfig
    redis: RedisConfig
    s3: S3Config
    auth: AuthConfig
    limits: LimitsConfig
    asr: ASRConfig
    diarization: DiarizationConfig
    llm: LLMConfig
    embeddings: EmbeddingsConfig
    admin_console: AdminConsoleConfig


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _limits_config_from_yaml(limits_data: Dict[str, Any]) -> LimitsConfig:
    """Merge YAML with defaults so older configs without realtime/autoprolong keys still load."""
    modes = limits_data.get("allowed_realtime_modes") or ["chunk", "windowed"]
    if isinstance(modes, list):
        modes = tuple(str(m) for m in modes)
    else:
        modes = ("chunk", "windowed")
    return LimitsConfig(
        max_duration_seconds=int(limits_data.get("max_duration_seconds", 7200)),
        max_file_size_bytes=int(limits_data.get("max_file_size_bytes", 524_288_000)),
        max_ttl_days=int(limits_data.get("max_ttl_days", 30)),
        allowed_realtime_modes=modes,
        default_realtime_mode=str(
            limits_data.get("default_realtime_mode", "chunk")
        ).lower(),
        chunk_ms_min=int(limits_data.get("chunk_ms_min", 500)),
        chunk_ms_max=int(limits_data.get("chunk_ms_max", 2000)),
        max_window_ms=int(limits_data.get("max_window_ms", 20_000)),
        autoprolong_enabled=bool(limits_data.get("autoprolong_enabled", False)),
        autoprolong_tail_seconds=float(
            limits_data.get("autoprolong_tail_seconds", 3.0)
        ),
    )


def _apply_env_overrides(server_data: Dict[str, Any]) -> None:
    """Override server.yaml with environment variables (e.g. for Docker)."""
    if os.environ.get("VT_DATABASE_URL"):
        server_data.setdefault("database", {})["url"] = os.environ["VT_DATABASE_URL"]
    if os.environ.get("VT_REDIS_URL"):
        server_data.setdefault("redis", {})["url"] = os.environ["VT_REDIS_URL"]
    s3 = server_data.get("s3") or {}
    if os.environ.get("VT_S3_ENDPOINT"):
        s3["endpoint"] = os.environ["VT_S3_ENDPOINT"]
    if os.environ.get("VT_S3_BUCKET"):
        s3["bucket"] = os.environ["VT_S3_BUCKET"]
    if os.environ.get("VT_S3_ACCESS_KEY"):
        s3["access_key"] = os.environ["VT_S3_ACCESS_KEY"]
    if os.environ.get("VT_S3_SECRET_KEY"):
        s3["secret_key"] = os.environ["VT_S3_SECRET_KEY"]
    server_data["s3"] = s3
    if os.environ.get("VT_ENVIRONMENT"):
        server_data["environment"] = os.environ["VT_ENVIRONMENT"]

    auth = server_data.setdefault("auth", {})
    google_auth = auth.setdefault("google", {})
    if os.environ.get("VT_GOOGLE_CLIENT_ID"):
        google_auth["client_id"] = os.environ["VT_GOOGLE_CLIENT_ID"]
    if os.environ.get("VT_GOOGLE_CLIENT_SECRET"):
        google_auth["client_secret"] = os.environ["VT_GOOGLE_CLIENT_SECRET"]
    yandex_auth = auth.setdefault("yandex", {})
    if os.environ.get("VT_YANDEX_CLIENT_ID"):
        yandex_auth["client_id"] = os.environ["VT_YANDEX_CLIENT_ID"]
    if os.environ.get("VT_YANDEX_CLIENT_SECRET"):
        yandex_auth["client_secret"] = os.environ["VT_YANDEX_CLIENT_SECRET"]
    server_data["auth"] = auth
    v = os.environ.get("VT_AUTH_LOCKOUT_ENABLED", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        lock = auth.setdefault("lockout", {})
        if isinstance(lock, dict):
            lock["enabled"] = False
    v2 = os.environ.get("VT_AUTH_LOGIN_AUDIT_ENABLED", "").strip().lower()
    if v2 in ("0", "false", "no", "off"):
        la = auth.setdefault("login_audit", {})
        if isinstance(la, dict):
            la["enabled"] = False
    rdays = os.environ.get("VT_AUTH_SIGNIN_EVENTS_RETENTION_DAYS", "").strip()
    if rdays.isdigit():
        la = auth.setdefault("login_audit", {})
        if isinstance(la, dict):
            la["retention_days"] = int(rdays)


def _asr_provider_config_from_dict(cfg: Dict[str, Any]) -> ASRProviderConfig:
    if not isinstance(cfg, dict):
        cfg = {}
    return ASRProviderConfig(
        enabled=bool(cfg.get("enabled", False)),
        model=cfg.get("model"),
        impl=cfg.get("impl"),
        model_path=cfg.get("model_path"),
    )


def _diarization_provider_config_from_dict(cfg: Dict[str, Any]) -> DiarizationProviderConfig:
    if not isinstance(cfg, dict):
        cfg = {}
    def _int_or_none(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None

    return DiarizationProviderConfig(
        enabled=bool(cfg.get("enabled", False)),
        impl=cfg.get("impl"),
        model=cfg.get("model"),
        device=cfg.get("device"),
        hf_token_env=cfg.get("hf_token_env"),
        offline_models=bool(cfg.get("offline_models", False)),
        model_cache_dir=cfg.get("model_cache_dir"),
        num_speakers=_int_or_none(cfg.get("num_speakers")),
        min_speakers=_int_or_none(cfg.get("min_speakers")),
        max_speakers=_int_or_none(cfg.get("max_speakers")),
    )


def _apply_diarization_env_overrides(diarization_data: Dict[str, Any]) -> None:
    v = os.environ.get("VT_DIARIZATION_TURN_LEVEL_RETRANSCRIPTION")
    if v is None or not str(v).strip():
        return
    diarization_data["turn_level_retranscription"] = str(v).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _apply_asr_env_overrides(asr_data: Dict[str, Any]) -> None:
    """Переопределения для configs/asr.yaml (модель и т.д.)."""
    if os.environ.get("VT_ASR_DEFAULT_PROVIDER"):
        asr_data["default_provider"] = os.environ["VT_ASR_DEFAULT_PROVIDER"].strip()
    if os.environ.get("VT_ASR_MODEL"):
        asr_data["recognition_model"] = os.environ["VT_ASR_MODEL"].strip()


def _embeddings_config_from_yaml(embeddings_data: Dict[str, Any]) -> EmbeddingsConfig:
    data = embeddings_data or {}
    openai_key = str(data.get("openai_api_key") or "").strip()
    if not openai_key:
        openai_key = (
            os.environ.get("VT_OPENAI_API_KEY", "").strip()
            or os.environ.get("OPENAI_API_KEY", "").strip()
        )
    return EmbeddingsConfig(
        enabled=bool(data.get("enabled", False)),
        provider=str(data.get("provider", "ollama") or "ollama").strip().lower(),
        model=str(data.get("model", "nomic-embed-text") or "nomic-embed-text").strip(),
        base_url=(
            str(data.get("base_url")).strip()
            if data.get("base_url")
            else None
        ),
        openai_base_url=(
            str(data.get("openai_base_url")).strip()
            if data.get("openai_base_url")
            else None
        ),
        openai_api_key=openai_key or None,
        timeout_seconds=float(data.get("timeout_seconds", 120)),
        max_input_chars=int(data.get("max_input_chars", 16_000)),
    )


def _apply_llm_env_overrides(llm_data: Dict[str, Any]) -> None:
    v = os.environ.get("VT_LLM_SESSION_SUMMARY_ENABLED", "").strip().lower()
    if v in ("1", "true", "yes"):
        llm_data["session_summary_enabled"] = True
    elif v in ("0", "false", "no"):
        llm_data["session_summary_enabled"] = False
    mc = os.environ.get("VT_LLM_SESSION_SUMMARY_MAX_INPUT_CHARS", "").strip()
    if mc.isdigit():
        llm_data["session_summary_max_input_chars"] = int(mc)
    # Docker/workers: localhost in llm.yaml points at the container itself; set e.g.
    # VT_OLLAMA_BASE_URL=http://host.docker.internal:11434 (Desktop) or http://ollama:11434.
    ollama_url = os.environ.get("VT_OLLAMA_BASE_URL", "").strip()
    ollama_model = os.environ.get("VT_OLLAMA_MODEL", "").strip()
    providers = llm_data.get("providers")
    if isinstance(providers, dict):
        om = providers.get("ollama")
        if isinstance(om, dict):
            if ollama_url:
                om["base_url"] = ollama_url
            if ollama_model:
                om["model"] = ollama_model


def _apply_embeddings_env_overrides(embeddings_data: Dict[str, Any]) -> None:
    v = os.environ.get("VT_EMBEDDINGS_ENABLED", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        embeddings_data["enabled"] = True
    elif v in ("0", "false", "no", "off"):
        embeddings_data["enabled"] = False
    if os.environ.get("VT_EMBEDDINGS_PROVIDER"):
        embeddings_data["provider"] = os.environ["VT_EMBEDDINGS_PROVIDER"].strip()
    if os.environ.get("VT_EMBEDDINGS_MODEL"):
        embeddings_data["model"] = os.environ["VT_EMBEDDINGS_MODEL"].strip()
    if os.environ.get("VT_OLLAMA_EMBEDDINGS_URL"):
        embeddings_data["base_url"] = os.environ["VT_OLLAMA_EMBEDDINGS_URL"].strip()


def _external_tools_from_yaml_list(raw: list[Any]) -> list[ExternalToolLink]:
    out: list[ExternalToolLink] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if name and url:
            out.append(ExternalToolLink(name=name, url=url))
    return out


def _admin_console_config(server_data: Dict[str, Any]) -> AdminConsoleConfig:
    """Ops console links (docs/ADMIN_OPS_CONSOLE.md); optional VT_ADMIN_EXTERNAL_TOOLS_JSON overrides YAML."""
    block = server_data.get("admin_console")
    if not isinstance(block, dict):
        block = {}
    tools_yaml = _external_tools_from_yaml_list(list(block.get("external_tools") or []))

    env_json = (os.environ.get("VT_ADMIN_EXTERNAL_TOOLS_JSON") or "").strip()
    if env_json:
        try:
            parsed = json.loads(env_json)
        except json.JSONDecodeError:
            parsed = []
        tools = (
            _external_tools_from_yaml_list(parsed)
            if isinstance(parsed, list)
            else []
        )
    else:
        tools = tools_yaml

    tmpl: str | None = None
    t = block.get("product_conversation_url_template")
    if isinstance(t, str) and t.strip():
        tmpl = t.strip()
    env_tmpl = (os.environ.get("VT_ADMIN_PRODUCT_CONVERSATION_URL_TEMPLATE") or "").strip()
    if env_tmpl:
        tmpl = env_tmpl
    webui = (os.environ.get("VT_WEBUI_ORIGIN") or "").strip().rstrip("/")
    if tmpl is None and webui:
        tmpl = f"{webui}/conversations/{{conversation_id}}"

    return AdminConsoleConfig(
        external_tools=tuple(tools),
        product_conversation_url_template=tmpl,
    )


@lru_cache(maxsize=1)
def load_app_config() -> ServerConfig:
    server_data = _load_yaml(CONFIG_DIR / "server.yaml")
    _apply_env_overrides(server_data)

    asr_data = _load_yaml(CONFIG_DIR / "asr.yaml")
    _apply_asr_env_overrides(asr_data)
    diarization_data = _load_yaml(CONFIG_DIR / "diarization.yaml")
    _apply_diarization_env_overrides(diarization_data)
    llm_data = _load_yaml(CONFIG_DIR / "llm.yaml")
    _apply_llm_env_overrides(llm_data)
    embeddings_data = _load_yaml(CONFIG_DIR / "embeddings.yaml")
    _apply_embeddings_env_overrides(embeddings_data)
    limits_data = _load_yaml(CONFIG_DIR / "limits.yaml")

    db_cfg = DatabaseConfig(**server_data["database"])
    redis_cfg = RedisConfig(**server_data["redis"])
    s3_cfg = S3Config(**server_data["s3"])

    def _oauth_from_yaml(block: Dict[str, Any]) -> OAuthProviderConfig:
        cid = block.get("client_id") or ""
        sec = block.get("client_secret") or ""
        if not isinstance(cid, str):
            cid = str(cid)
        if not isinstance(sec, str):
            sec = str(sec)
        return OAuthProviderConfig(client_id=cid.strip(), client_secret=sec.strip())

    auth_raw = server_data.get("auth") or {}
    if not isinstance(auth_raw, dict):
        auth_raw = {}
    lock_raw = auth_raw.get("lockout") or {}
    if not isinstance(lock_raw, dict):
        lock_raw = {}
    la_raw = auth_raw.get("login_audit") or {}
    if not isinstance(la_raw, dict):
        la_raw = {}
    lock_cfg = AuthLockoutConfig(
        enabled=bool(lock_raw.get("enabled", True)),
        refresh_invalid_max_per_ip=int(lock_raw.get("refresh_invalid_max_per_ip", 40)),
        api_key_invalid_max_per_ip=int(lock_raw.get("api_key_invalid_max_per_ip", 80)),
        window_seconds=int(lock_raw.get("window_seconds", 900)),
        block_seconds=int(lock_raw.get("block_seconds", 900)),
    )
    try:
        rd = int(la_raw.get("retention_days", 90))
    except (TypeError, ValueError):
        rd = 90
    login_audit_cfg = AuthLoginAuditConfig(
        enabled=bool(la_raw.get("enabled", True)),
        include_client_fingerprint=bool(la_raw.get("include_client_fingerprint", True)),
        retention_days=max(0, rd),
    )
    auth_cfg = AuthConfig(
        google=_oauth_from_yaml(auth_raw["google"]),
        yandex=_oauth_from_yaml(auth_raw["yandex"]),
        lockout=lock_cfg,
        login_audit=login_audit_cfg,
    )

    limits_cfg = _limits_config_from_yaml(limits_data)

    asr_providers = {
        name: _asr_provider_config_from_dict(cfg)
        for name, cfg in (asr_data.get("providers") or {}).items()
    }
    rec_model = asr_data.get("recognition_model")
    if rec_model is not None and not isinstance(rec_model, str):
        rec_model = str(rec_model)
    asr_cfg = ASRConfig(
        default_provider=str(asr_data.get("default_provider", "") or "").strip(),
        recognition_model=(rec_model.strip() if rec_model else None),
        providers=asr_providers,
    )

    llm_providers: Dict[str, LLMProviderConfig] = {}
    for name, raw in (llm_data.get("providers") or {}).items():
        if not isinstance(raw, dict):
            continue
        llm_providers[name] = LLMProviderConfig(
            enabled=bool(raw.get("enabled", False)),
            base_url=raw.get("base_url"),
            model=raw.get("model"),
            api_key=raw.get("api_key"),
        )
    llm_cfg = LLMConfig(
        default_provider=llm_data.get("default_provider", ""),
        providers=llm_providers,
        session_summary_enabled=bool(llm_data.get("session_summary_enabled", False)),
        session_summary_max_input_chars=int(
            llm_data.get("session_summary_max_input_chars", 120_000) or 120_000
        ),
    )

    embeddings_cfg = _embeddings_config_from_yaml(embeddings_data)

    diarization_providers = {
        name: _diarization_provider_config_from_dict(cfg)
        for name, cfg in (diarization_data.get("providers") or {}).items()
    }
    diarization_cfg = DiarizationConfig(
        enabled=bool(diarization_data.get("enabled", False)),
        default_provider=(
            str(diarization_data.get("default_provider", "") or "").strip() or None
        ),
        providers=diarization_providers,
        turn_level_retranscription=bool(
            diarization_data.get("turn_level_retranscription", False)
        ),
    )

    admin_console_cfg = _admin_console_config(server_data)

    return ServerConfig(
        environment=server_data.get("environment", "development"),
        host=server_data.get("host", "0.0.0.0"),
        port=int(server_data.get("port", 8000)),
        database=db_cfg,
        redis=redis_cfg,
        s3=s3_cfg,
        auth=auth_cfg,
        limits=limits_cfg,
        asr=asr_cfg,
        diarization=diarization_cfg,
        llm=llm_cfg,
        embeddings=embeddings_cfg,
        admin_console=admin_console_cfg,
    )


app_config: ServerConfig = load_app_config()

