## Documentation

- **[TECHNICAL_SPECIFICATION.md](./TECHNICAL_SPECIFICATION.md)** — техническое задание (канон). Сегментация по времени, **fast/final**, **`finalize`**, `meta` / `kind`: **§17**.
- **[ROADMAP.md](./ROADMAP.md)** — дорожная карта и пометки по реализации.
- **[OPENAPI.md](./OPENAPI.md)** — как проверять [`../openapi.yaml`](../openapi.yaml).
- **[TESTING.md](./TESTING.md)** — pytest e2e Phase A (A3.2), переменные `VT_E2E_*`.
- **[WEBSOCKET.md](./WEBSOCKET.md)** — контракт WebSocket (Phase B): `/ws/audio`, `/ws/transcript`, JWT.
- **[BROWSER_EXTENSION_UI.md](./BROWSER_EXTENSION_UI.md)** — соглашения по UI расширения (Side Panel, popup, контекстное меню, persist состояния).
- **[AUTH_AND_IDENTITY.md](./AUTH_AND_IDENTITY.md)** — OAuth, идентичность, сессия сервиса (расширение + Web UI), слияние аккаунтов в Web UI.
- **[MODEL_CONFIGURATION.md](./MODEL_CONFIGURATION.md)** — где и как настраиваются модели/провайдеры (ASR/diarization/embeddings/LLM) и параметры автопродления.
- **[ASR_PROVIDER_IMPLEMENTATION.md](./ASR_PROVIDER_IMPLEMENTATION.md)** — план подключения реальных ASR-провайдеров (Phase B, B1.5).
- **[DIARIZATION_ALIGNMENT_VERSIONING.md](./DIARIZATION_ALIGNMENT_VERSIONING.md)** — дизайн diarization/alignment и схема хранения версий транскриптов (active pointer); `turn_level_retranscription`, Web UI override, `POST …/retranscribe`.
- **[PHASE_A_ACCEPTANCE.md](./PHASE_A_ACCEPTANCE.md)** — ручной чеклист приёмки Phase A (в т.ч. загрузка файла и запись с микрофона).
- **[PHASE_B_ACCEPTANCE.md](./PHASE_B_ACCEPTANCE.md)** — ручной чеклист приёмки Phase B (realtime WS, расширение Chromium, автотесты `browser-extension`).
- **[PHASE_C_ACCEPTANCE.md](./PHASE_C_ACCEPTANCE.md)** — приёмка блока **C7 + родительский C1**: порядок проверки OAuth/refresh/WS, diarization pipeline, ссылки на автотесты.
- **[adr/](./adr/)** — архитектурные решения (ADR).
- **[ADMIN_OPS_CONSOLE.md](./ADMIN_OPS_CONSOLE.md)** — требования **v1.0 (baseline)** к отдельной Ops-консоли; **фактическая реализация** и backlog — §4.2, чеклисты [ADMIN_OPS_SPRINT2_CHECKLIST.md](./ADMIN_OPS_SPRINT2_CHECKLIST.md) … [ADMIN_OPS_SPRINT8_CHECKLIST.md](./ADMIN_OPS_SPRINT8_CHECKLIST.md), [ADMIN_OPS_ROADMAP.md](./ADMIN_OPS_ROADMAP.md). Код: `server/admin_api/`, `admin-webui/`, маршруты в [`../openapi.yaml`](../openapi.yaml).

### Phase C (C2–C6): настройки и где смотреть

| Область | Файл / эндпоинт | Переменные окружения (часть) |
|--------|------------------|-------------------------------|
| Семантический поиск (эмбеддинги) | [`configs/embeddings.yaml`](../configs/embeddings.yaml) | `VT_EMBEDDINGS_ENABLED`, `VT_EMBEDDINGS_PROVIDER`, `VT_EMBEDDINGS_MODEL`, `VT_OLLAMA_EMBEDDINGS_URL`, `VT_OPENAI_API_KEY` / `OPENAI_API_KEY` |
| Автопродление realtime (ТЗ раздел 7) | [`configs/limits.yaml`](../configs/limits.yaml) (`autoprolong_*`, лимиты длительности/размера) | см. `LimitsConfig` в [`server/core/config.py`](../server/core/config.py) |
| Протокол WS при ротации | [WEBSOCKET.md — автопродление](./WEBSOCKET.md) | — |
| Метрики Prometheus | **`GET /metrics`** на API | стандартные счётчики/гистограммы (`prometheus_client`) |
| CLI / API key | скрипт [`scripts/issue_api_key.py`](../scripts/issue_api_key.py); заголовок **`X-VT-Api-Key`** | `VT_API_KEY` в CLI; таблица БД `user_api_keys` (миграция `c6_api_keys_001`) |

Индексация эмбеддингов ставится в очередь **`llm`** (тот же worker, что и задачи LLM) — см. [`server/workers/celery_app.py`](../server/workers/celery_app.py).

### Где задаются **модели** (ASR / диаризация / эмбеддинги / LLM)

| Назначение | Конфиг | Документация / код |
|------------|--------|-------------------|
| **ASR** (Whisper / faster-whisper / Vosk и т.д.) | [`configs/asr.yaml`](../configs/asr.yaml): `default_provider`, `recognition_model`, `providers.*` | [ASR_PROVIDER_IMPLEMENTATION.md](./ASR_PROVIDER_IMPLEMENTATION.md), [`server/app/asr/factory.py`](../server/app/asr/factory.py); env: `VT_ASR_DEFAULT_PROVIDER`, `VT_ASR_MODEL`, см. [docker/README.md](../docker/README.md) |
| **Диаризация** (pyannote и др.) | [`configs/diarization.yaml`](../configs/diarization.yaml) | [DIARIZATION_ALIGNMENT_VERSIONING.md](./DIARIZATION_ALIGNMENT_VERSIONING.md), [docker/README.md](../docker/README.md) (профиль `diarization`, CPU/GPU образы) |
| **Эмбеддинги текста** (семантический поиск; не ASR) | [`configs/embeddings.yaml`](../configs/embeddings.yaml): `provider`, `model`, `base_url` | [`server/core/embedding_client.py`](../server/core/embedding_client.py) |
| **LLM** (summary и др., если используете) | [`configs/llm.yaml`](../configs/llm.yaml) | [`server/workers/tasks/llm.py`](../server/workers/tasks/llm.py), плагины в `plugins/` |

**Пакетная загрузка аудио (Web UI / CLI):** один контракт **`POST /api/upload`** — см. §3.3 в ТЗ, раздел «Паритет» и установка в [`../cli/README.md`](../cli/README.md). В Web UI: файл с диска или запись с микрофона до остановки — [`../webui/src/pages/ConversationsPage.tsx`](../webui/src/pages/ConversationsPage.tsx), хук [`../webui/src/hooks/useMicrophoneRecorder.ts`](../webui/src/hooks/useMicrophoneRecorder.ts). CLI: `pip install -e ./cli`, команда **`transcriber`**.

Дополнительно: корневой `README.md`, `main_prompt*.txt`, `naive_prompt*.txt`.

