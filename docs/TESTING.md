# Тестирование

## Phase C — приёмка C7 + C1 (ручная + автотесты)

Чеклист и порядок ручной проверки: **[PHASE_C_ACCEPTANCE.md](./PHASE_C_ACCEPTANCE.md)**.  
Автотесты без поднятого Docker: `poetry run pytest tests/unit/ -v` (сервер), `npm run test` в `browser-extension/`.

## A3.2 — интеграционный сценарий Phase A (upload → транскрипт → export)

Файл: `server/tests/integration/test_phase_a_upload_export_e2e.py`

Проверяет цепочку **POST /api/upload** → обработка воркером Celery (stub ASR) → **GET /api/conversations/{id}** с непустым `transcript` → **GET .../export?format=md** с ожидаемым текстом stub.

### Требования

- Запущены **API**, **Celery worker**, **PostgreSQL**, **Redis**, **MinIO** (как в `docker/docker-compose.yml` или локально).
- Типичный URL API после `docker compose up` из `docker/`: **`http://127.0.0.1:8002`** (не 8000 — см. проброс портов в [docker/README.md](../docker/README.md)).
- В БД есть пользователь, для которого валиден JWT.
- Переменные окружения:
  - **`VT_E2E_BASE_URL`** — базовый URL API **без** суффикса `/api` (например `http://127.0.0.1:8002`).
  - **`VT_E2E_TOKEN`** — Bearer JWT (в Web UI: `localStorage` → `access_token`).

Опционально: **`VT_E2E_POLL_INTERVAL`** (сек, по умолчанию `2`), **`VT_E2E_MAX_WAIT`** (сек, по умолчанию `120`).

### Запуск

```bash
cd server
set VT_E2E_BASE_URL=http://127.0.0.1:8002
set VT_E2E_TOKEN=<JWT>
poetry run pytest tests/integration/test_phase_a_upload_export_e2e.py -v -m e2e
```

Без `VT_E2E_*` тест **пропускается** (`skip`), чтобы обычный `pytest` на машине без стека не падал.

### Сводный отчёт по вашим аудиофайлам (`scripts/audio_acceptance_report.py`)

Один скрипт гоняет **POST /api/upload** для каждого переданного файла (или одну встроенную заглушку, если файлов нет), ждёт непустой `transcript` в режиме **tier=auto**, затем проверяет:

- **GET** с **tier=fast** — пустой список сегментов (для upload-only отдельная fast-ветка не создаётся; см. [WEBSOCKET.md](./WEBSOCKET.md));
- **GET** с **tier=final** — непустой транскрипт после обработки воркером;
- **export** `format=json` — **tier=final** даёт 200, **tier=fast** даёт **404**.

Опционально: **`--realtime-webm путь`** — создаётся разговор, открывается **WebSocket** `/ws/audio/{id}`, в канал отправляется файл по частям и JSON **`finalize`**; дальше проверяется наличие данных в **tier=fast/final** и успешный export (после finalize fast-строка есть). Нужен пакет **`websockets`** (зависимость dev в `server/pyproject.toml`).

Переменные (дублируют smoke/e2e): **`VT_E2E_BASE_URL`** или **`VT_API_BASE_URL`**, **`VT_E2E_TOKEN`** или **`VT_ACCESS_TOKEN`**; **`VT_E2E_POLL_INTERVAL`**, **`VT_E2E_MAX_WAIT`**.

Пример:

```bash
cd server
set VT_E2E_BASE_URL=http://127.0.0.1:8002
set VT_E2E_TOKEN=<JWT>
python ..\scripts\audio_acceptance_report.py my.wav clip.webm --json-out
```

Интеграционная обёртка pytest: `server/tests/integration/test_audio_acceptance_report.py`, маркер **`audio_acceptance`**.

- Без **`VT_E2E_ACCEPTANCE_FILES`** второй тест использует **`server/tests/sample-1.webm`**, если файл есть; иначе **skip**.
- Для realtime добавьте **`VT_E2E_REALTIME_WEBM`** (путь к WebM) — обёртка передаст **`--realtime-webm`**.

```bash
cd server
set VT_E2E_BASE_URL=http://127.0.0.1:8002
set VT_E2E_TOKEN=<JWT>
set VT_E2E_ACCEPTANCE_FILES=C:\path\a.wav,C:\path\b.webm
set VT_E2E_REALTIME_WEBM=C:\path\session.webm
poetry run pytest tests/integration/test_audio_acceptance_report.py -v -m audio_acceptance
```

### Ручная регрессия: повторный ASR и diarization

При поднятом стеке и JWT в Web UI:

0. Если вы запускаете стек через `docker/`, убедитесь, что diarization-воркер поднят (он опциональный и в compose профиле `diarization`):

   ```bash
   cd docker
   docker compose --profile diarization up -d --build diarization-worker
   ```

1. **Settings** — серверный дефолт «Diarization re-ASR per turn» в блоке **Server limits**; опционально включите **Custom diarization** и сохраните.
2. На странице разговора с загруженным аудио — **Transcribe again** (`POST /api/conversations/{id}/retranscribe`): ожидается новая ревизия `asr`, при `diarization.enabled` — последующая постановка diarization.
3. **Diarize again** — по-прежнему только post-hoc diarization (`POST …/diarize`). Поведение текста при `turn_level_retranscription: false` — см. [DIARIZATION_ALIGNMENT_VERSIONING.md](./DIARIZATION_ALIGNMENT_VERSIONING.md) §2.3.

Юнит-тест логики merge prefs: `server/tests/unit/test_diarization_prefs.py`.

### Лёгкий юнит-тест (без Docker / без импорта workers)

`server/tests/unit/test_stub_transcript_source.py` — убеждается, что в `workers/tasks/asr.py` по-прежнему есть маркер stub-транскрипта (импорт `workers.tasks` при старте pytest поднимает S3, поэтому проверяем файл на диске).

```bash
cd server
poetry run pytest tests/unit/ -v
```

## B3.4 — реальный ASR (unit, `sample-1.webm`)

Файлы: `server/tests/unit/test_asr_inference_b34.py`, часть проверок в `test_asr_registry.py`.

- Нужны **ffmpeg** в `PATH` и сеть при первом запуске (скачивание моделей faster-whisper с Hugging Face).
- Маркер pytest: **`asr_inference`**. Пропуск тяжёлых тестов: **`VT_SKIP_ASR_INFERENCE=1`**.
- **Vosk:** тест выполняется только при **`VOSK_MODEL_PATH`** — путь к распакованной модели ([vosk-model](https://alphacephei.com/vosk/models)); иначе `skip`.

Запуск только ASR-тестов:

```bash
cd server
poetry run pytest -m asr_inference -v
```

## Все тесты сервера

```bash
cd server
poetry run pytest
```

## Phase B — юнит-тесты расширения браузера (Vitest)

Каталог: [`../browser-extension/`](../browser-extension/). Проверяют чистую логику без запуска Chromium: `inferAudioFormatFromFilename`, `parseOAuthRedirect` / `buildProviderAuthUrl`, HTTP-обёртки `getConversationDetail` / `fetchConversationExport`, persist сессии с моком `chrome.storage.local`.

### Запуск

```bash
cd browser-extension
npm ci
npm run test
npm run build
```

Ручная приёмка Phase B (расширение + WS + backend): [PHASE_B_ACCEPTANCE.md](./PHASE_B_ACCEPTANCE.md).
