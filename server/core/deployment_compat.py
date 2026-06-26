"""
Deployment vs configuration compatibility (ADMIN_OPS sprint 9 precursor).

Detects mismatches such as GigaAM in ASR config on a CPU compose profile,
or diarization enabled without a queue consumer.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from typing import Literal

from core.config import app_config

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class CompatibilityIssue:
    code: str
    severity: Severity
    message: str
    hint: str | None = None


@dataclass(frozen=True)
class QueueConsumerSlice:
    queue: str
    consumer_responding: bool


def deploy_profile() -> str:
    """Compose / runtime label: ``cpu`` (default stack) or ``gpu``."""
    return (os.environ.get("VT_DEPLOY_PROFILE") or "cpu").strip().lower()


def gigaam_importable() -> bool:
    return importlib.util.find_spec("gigaam") is not None


def _effective_asr_provider_names() -> list[tuple[str, str]]:
    cfg = app_config.asr
    pairs: list[tuple[str, str]] = []
    for tier, raw in (
        ("realtime", cfg.realtime_provider or cfg.default_provider),
        ("final", cfg.final_provider or cfg.default_provider),
    ):
        name = (raw or "").strip().lower()
        if name:
            pairs.append((tier, name))
    return pairs


def _gigaam_longform_expected() -> bool:
    gp = app_config.asr.providers.get("gigaam")
    if gp is None or not gp.enabled:
        return False
    env = os.environ.get("VT_GIGAAM_LONGFORM")
    if env is not None and str(env).strip():
        return str(env).strip().lower() in ("1", "true", "yes", "on")
    if gp.longform_enabled is not None:
        return bool(gp.longform_enabled)
    return True


def _hf_token_present() -> bool:
    gp = app_config.asr.providers.get("gigaam")
    token_env = "VT_HF_TOKEN"
    if gp is not None and gp.hf_token_env:
        token_env = str(gp.hf_token_env).strip()
    return bool(os.environ.get(token_env, "").strip())


def collect_compatibility_issues(
    *,
    celery_queues: list[QueueConsumerSlice] | None = None,
) -> list[CompatibilityIssue]:
    issues: list[CompatibilityIssue] = []
    profile = deploy_profile()
    queues = celery_queues or []

    def _queue(name: str) -> QueueConsumerSlice | None:
        for q in queues:
            if q.queue == name:
                return q
        return None

    for tier, provider in _effective_asr_provider_names():
        if provider != "gigaam":
            continue
        if profile == "cpu":
            issues.append(
                CompatibilityIssue(
                    code="gigaam_requires_gpu_stack",
                    severity="error",
                    message=(
                        f"Конфиг ASR ({tier}) использует GigaAM, "
                        f"но VT_DEPLOY_PROFILE=cpu (CPU-стек без пакета gigaam)."
                    ),
                    hint=(
                        "Для dev на CPU: VT_ASR_FINAL_PROVIDER=whisper (docker/.env) и "
                        "docker compose up -d --force-recreate worker-final. "
                        "Для GigaAM: profile gpu, worker-final-gpu, VT_DEPLOY_PROFILE=gpu."
                    ),
                )
            )
        elif not gigaam_importable():
            issues.append(
                CompatibilityIssue(
                    code="gigaam_package_missing",
                    severity="error",
                    message=(
                        f"Конфиг ASR ({tier}) использует GigaAM, "
                        "но пакет gigaam не установлен в этом процессе."
                    ),
                    hint="Соберите образ worker-final-gpu (Dockerfile.ml-base) или poetry install --with gigaam.",
                )
            )

        if _gigaam_longform_expected() and not _hf_token_present():
            issues.append(
                CompatibilityIssue(
                    code="gigaam_longform_missing_hf_token",
                    severity="warning",
                    message="GigaAM longform включён, но HF-токен не задан (VT_HF_TOKEN).",
                    hint="Задайте VT_HF_TOKEN в docker/.env для длинных файлов.",
                )
            )

        asr_final = _queue("asr_final")
        if asr_final is not None and not asr_final.consumer_responding:
            issues.append(
                CompatibilityIssue(
                    code="asr_final_no_consumer",
                    severity="error",
                    message="Очередь asr_final без активного Celery consumer — batch/final ASR не выполнится.",
                    hint="Поднимите worker-final (CPU) или worker-final-gpu (profile gpu).",
                )
            )

    if app_config.diarization.enabled:
        diar = _queue("diarization")
        if diar is not None and not diar.consumer_responding:
            issues.append(
                CompatibilityIssue(
                    code="diarization_no_consumer",
                    severity="warning",
                    message="Диаризация включена в конфиге, но очередь diarization без consumer.",
                    hint="docker compose --profile diarization up -d diarization-worker",
                )
            )

    # Both CPU and GPU final workers on asr_final is a documented anti-pattern.
    if profile == "gpu":
        asr_q = _queue("asr")
        if asr_q is not None and asr_q.consumer_responding:
            main_has_asr_fast = _queue("asr_fast")
            if main_has_asr_fast is not None and main_has_asr_fast.consumer_responding:
                issues.append(
                    CompatibilityIssue(
                        code="gpu_split_check_main_worker",
                        severity="warning",
                        message=(
                            "GPU-профиль: основной worker всё ещё слушает asr/asr_fast. "
                            "Возможна конкуренция с worker-final-gpu."
                        ),
                        hint="Уберите asr_fast из VT_MAIN_WORKER_QUEUES; остановите worker-final (CPU).",
                    )
                )

    return issues


def log_compatibility_issues(issues: list[CompatibilityIssue], *, logger) -> None:
    for item in issues:
        line = f"[deploy-compat] {item.severity.upper()} {item.code}: {item.message}"
        if item.hint:
            line += f" — {item.hint}"
        if item.severity == "error":
            logger.error(line)
        else:
            logger.warning(line)
