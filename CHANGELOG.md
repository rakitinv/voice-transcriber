# Changelog

Все заметные изменения проекта фиксируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии следуют [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Added

### Changed

### Fixed

### Removed

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

[Unreleased]: https://github.com/rakitinv/voice-transcriber/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/rakitinv/voice-transcriber/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rakitinv/voice-transcriber/releases/tag/v0.1.0
