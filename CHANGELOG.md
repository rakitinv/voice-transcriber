# Changelog

Все заметные изменения проекта фиксируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии следуют [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Added

### Changed

### Fixed

### Removed

## [0.3.3] - 2026-06-30

### Added

- Расширение браузера: API-клиент сводки сессии — `getSessionSummary`, `retrySessionSummary`, `pollSessionSummary`; `getServerLimits` (`llm_session_summary_enabled`).

### Changed

- Расширение браузера: **«Сохранить живой текст»** активна только при непустом тексте в области транскрипта.
- Расширение браузера: **«Сгенерировать сводку»** переименована в **«Получить сводку»**; кнопка доступна при активном разговоре и включённой сводке на сервере; поведение как в Web UI (GET `/session-summary`, retry при `failed`, polling при `pending`/`running`); блок отображения скользящей сводки.

## [0.3.2] - 2026-06-30

### Added

- **Realtime v2 (R1–R6):** [REALTIME_FAST_FINAL_V2.md](docs/REALTIME_FAST_FINAL_V2.md) — дефолт **`windowed`**, **`finalize`** в расширении вместо дублирующего upload, периодический persist **fast** в БД (`fast_persist_interval_s`), разделение **`media_chunk_ms`** / **`asr_step_ms`**, overlap окон ASR и merge partials по таймкодам (`core/realtime_merge.py`), событие WS **`fast_snapshot`**.
- API: поля `asr_step_ms`, `media_chunk_ms` в `POST /api/conversations`; `media_chunk_ms_max` в limits; опциональные env `VT_LIMITS_CHUNK_MS_MAX`, `VT_LIMITS_MEDIA_CHUNK_MS_MAX`, `VT_FAST_PERSIST_*`, `VT_REALTIME_FAST_VIA_CELERY`.
- Docker: [`docker/compose.api-gpu.override.yml`](docker/compose.api-gpu.override.yml) для CUDA realtime на `api`; раздел в [`docker/README.md`](docker/README.md).
- Upload: идемпотентность при повторной загрузке после `finalize`.
- Unit-тесты: `test_realtime_merge.py`, `test_realtime_fast_persist.py`, `test_conversation_realtime_fields.py`.

### Changed

- Расширение: `finalize` + `finalize_ack` перед закрытием WS; fallback upload только при сбое finalize; дефолты `realtimeMode: windowed`, `asrStepMs: 2500`, `mediaChunkMs: 1000`.
- Web UI: poll и подсказка «черновик обновляется» на вкладке Fast во время записи.
- `configs/limits.yaml`: `chunk_ms_max: 3000` (кламп `asr_step_ms`), `window_overlap_ms`, `fast_persist_*`, `default_realtime_mode: windowed`.
- `transcript_partial` в WS: поля `start` / `end`.
- [`docs/ROADMAP.md`](docs/ROADMAP.md): R1–R6 отмечены выполненными.

### Fixed

- UTF-8 BOM убран из `pyproject.toml` / `package.json` (ломали Poetry и Vitest на Windows).

## [0.3.1] - 2026-06-30

### Added

- **C1.4 — идентификация и переименование спикеров:** `speaker_labels` и `speaker_identification_status` на `conversations`, ядро `core/speaker_labels.py`, API `GET/PATCH /speakers`, `POST …/identify`, `POST …/apply-suggestions`, Celery `identify_speakers`, интеграция с диаризацией и сводками LLM.
- Web UI: панель **«Спикеры»** (`SpeakerPanel`) на странице разговора — ручное переименование, приём предложений LLM, автообновление расшифровки после сохранения.
- Конфиг `speaker_identification` в `configs/llm.yaml`; acceptance-тесты и [`docs/SPEAKER_IDENTIFICATION_ACCEPTANCE.md`](docs/SPEAKER_IDENTIFICATION_ACCEPTANCE.md).

### Changed

- `GET /conversations/{id}` и export: отображаемые имена спикеров из `speaker_labels`, `speaker_id` в сегментах.
- Панель спикеров: стиль под тёмную тему расшифровки; после переименования акцент на текущем имени, ID диаризации — мелким серым.
- GigaAM (HF): `low_cpu_mem_usage=False` при загрузке модели (обход meta-device в transformers 5.x).
- `docker-compose.yml`: `VT_GIGAAM_FP16_ENCODER=0` по умолчанию на GPU final-воркерах (cuFFT / fp16 STFT).

### Fixed

- Web UI: refetch разговора после PATCH спикеров (неверный query key React Query).
- GigaAM: загрузка весов с Hugging Face (`ai-sage/GigaAM-v3`) и совместимость с deployment_compat.

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

[Unreleased]: https://github.com/rakitinv/voice-transcriber/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/rakitinv/voice-transcriber/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/rakitinv/voice-transcriber/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rakitinv/voice-transcriber/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rakitinv/voice-transcriber/releases/tag/v0.1.0
