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

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

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
class AuthConfig:
    """Loaded from configs/server.yaml (auth.google / auth.yandex), not from Python defaults."""

    google: OAuthProviderConfig
    yandex: OAuthProviderConfig

@dataclass
class LimitsConfig:
    max_duration_seconds: int
    max_file_size_bytes: int
    max_ttl_days: int


@dataclass
class ASRProviderConfig:
    enabled: bool
    model: str | None = None
    impl: str | None = None  # dotted path to implementation, optional


@dataclass
class LLMProviderConfig:
    enabled: bool
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


@dataclass
class ASRConfig:
    default_provider: str
    providers: Dict[str, ASRProviderConfig]


@dataclass
class LLMConfig:
    default_provider: str
    providers: Dict[str, LLMProviderConfig]


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
    llm: LLMConfig


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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


@lru_cache(maxsize=1)
def load_app_config() -> ServerConfig:
    server_data = _load_yaml(CONFIG_DIR / "server.yaml")
    _apply_env_overrides(server_data)

    asr_data = _load_yaml(CONFIG_DIR / "asr.yaml")
    llm_data = _load_yaml(CONFIG_DIR / "llm.yaml")
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

    auth_cfg = AuthConfig(
        google=_oauth_from_yaml(server_data["auth"]["google"]),
        yandex=_oauth_from_yaml(server_data["auth"]["yandex"]),
    )

    limits_cfg = LimitsConfig(**limits_data)

    asr_providers = {
        name: ASRProviderConfig(**cfg)
        for name, cfg in asr_data.get("providers", {}).items()
    }
    asr_cfg = ASRConfig(
        default_provider=asr_data.get("default_provider", ""),
        providers=asr_providers,
    )

    llm_providers = {
        name: LLMProviderConfig(**cfg)
        for name, cfg in llm_data.get("providers", {}).items()
    }
    llm_cfg = LLMConfig(
        default_provider=llm_data.get("default_provider", ""),
        providers=llm_providers,
    )

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
        llm=llm_cfg,
    )


app_config: ServerConfig = load_app_config()

