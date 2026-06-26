# Changelog

Все заметные изменения проекта фиксируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии следуют [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Added

### Changed

### Fixed

### Removed

## [0.3.0] - 2026-06-25

### Added

- Единый **`poetry.lock`** на Python **3.12** для API, worker, diarization и GigaAM; документация [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md), [`docs/DEPENDENCIES_MIGRATION.md`](docs/DEPENDENCIES_MIGRATION.md).
- Образ **`Dockerfile.ml-base`** (`ml-base-cpu` / `ml-base-cuda`): общий ML runtime (Poetry main + diarization + gigaam + `install-torch.sh`).
- Скрипты **`docker/scripts/install-torch.sh`**, **`pip-retry.sh`**; CI job **`ml-base-docker`** в [`.github/workflows/server-deps.yml`](.github/workflows/server-deps.yml).
- **Unified GPU worker**: сервис `worker-gpu-unified`, профиль `gpu-unified`, `VT_GPU_DEPLOY_MODE`, [`server/workers/gpu_unified_entrypoint.py`](server/workers/gpu_unified_entrypoint.py).
- Release-автоматизация: `build-all.*`, `package-release.*`, `install-or-update.sh`, `push-registry.sh`, [`docs/Памятка по сборке и развертыванию.md`](docs/Памятка%20по%20сборке%20и%20развертыванию.md).
- Плагин LLM **OpenAI-compatible** (`server/plugins/openai_chat_llm.py`); `deployment_compat` и снимок совместимости в Admin API.
- Admin Web UI: **`VITE_ADMIN_WEBUI_BASE_PATH`** для деплоя за reverse proxy (`/admin/`).
- Расширение: дефолтный Server URL из **`VITE_DEFAULT_SERVER_URL`** при сборке.

### Changed

- **pyannote.audio 4.x**, **torch/torchaudio 2.10**, **numpy 2.x**, **huggingface-hub 1.x**; GigaAM в Poetry group `gigaam` (без отдельного `pip install` в GPU Dockerfile).
- Child-образы GPU/diarization собираются targets в `Dockerfile.ml-base`; тонкие `Dockerfile.diarization` / `Dockerfile.worker.gpu` для registry с `ML_BASE_IMAGE`.
- `install-or-update.sh`: нормализация GPU-профилей (split vs unified), взаимоисключение воркеров.
- CI **release-artifacts** и CLI: Python **3.12**.

### Fixed

- OAuth admin Web UI: корректный landing URL при SPA не в корне домена (`adminSelfLandingUrl`, Vite `base`).

## [0.2.0] - 2026-06-22

### Added

- Провайдер ASR **GigaAM** (`gigaam`) для русской речи: `server/app/asr/gigaam.py`, longform и chunking в `gigaam_engine.py`.
- Раздельная настройка движка ASR для **realtime** и **final**: `realtime_provider` / `final_provider` в `configs/asr.yaml`, env `VT_ASR_REALTIME_*` / `VT_ASR_FINAL_*`, резолв в `core/asr_tier.py`.
- Optional Poetry-группа `gigaam`, образ `worker-final-gpu` с CUDA torch и longform extra.
- Документация [`docs/GIGAAM_ASR.md`](docs/GIGAAM_ASR.md), unit-тесты `test_gigaam_provider.py`, `test_asr_tier.py`.
- Файлы **`VERSION`** и **`CHANGELOG.md`**, процесс версионирования в [`docs/VERSIONING.md`](docs/VERSIONING.md).

### Changed

- Дефолт ASR: **whisper** (realtime / WebSocket), **GigaAM** `v3_e2e_rnnt` (final / Celery).
- Admin API / OpenAPI: поля tier-провайдеров в снимке пайплайна.
- `docker-compose.yml`: tier env на `api` и `worker-final-gpu` без жёсткого override final на faster-whisper.

## [0.1.0] - 2026-04-18

### Added

- MVP: сервер (FastAPI, Celery), Web UI, расширение браузера, CLI, Docker Compose.
- ASR: whisper, faster-whisper, vosk; post-hoc diarization (pyannote).
- Realtime WebSocket, версионирование транскриптов, admin-webui и admin-api.
- Документация в `docs/`, release-скрипты в `scripts/release/`.

[Unreleased]: https://github.com/rakitinv/voice-transcriber/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/rakitinv/voice-transcriber/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rakitinv/voice-transcriber/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rakitinv/voice-transcriber/releases/tag/v0.1.0
