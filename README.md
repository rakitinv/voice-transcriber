## Voice Transcriber

Репозиторий — **сервер**, **Web UI**, **расширение браузера**, **CLI**, конфигурации и **Docker** для локального и продакшен-подобного развёртывания. Подробности по модулям — в `docs/` и README внутри каталогов.

### High-level Architecture

- **Backend (`server/`)**: FastAPI API, Celery workers, Redis, PostgreSQL, MinIO-compatible S3, plugin architecture for ASR, diarization, and LLM providers.
- **Web UI (`webui/`)**: React + Vite + TypeScript single-page application.
- **Browser Extension (`browser-extension/`)**: Chromium extension for realtime recording and transcription.
- **CLI Client (`cli/`)**: Installable **`transcriber`** command (`pip install -e ./cli`) — upload, conversations, export, audio download; same API as Web UI (see `cli/README.md`).
- **Configs (`configs/`)**: YAML configuration files for server, ASR, diarization, embeddings (semantic search), LLM, limits.
- **Docker (`docker/`)**: `docker-compose` and service-level Dockerfiles for local deployment.
- **Docs (`docs/`)**: Technical specification, WebSocket contract, auth, Ops console, ADRs, and acceptance checklists.

### Ops / Admin console

Отдельная **операторская** поверхность поверх той же инфраструктуры, что и основной продукт (не второй продукт и не дублирование пользовательских сценариев загрузки).

| Слой | Роль |
|------|------|
| **`admin-webui/`** | Отдельный SPA (React + Vite): список разговоров и карточка **только с техническими полями**, инфраструктура, аудит, снимок пайплайна, лента `pipeline-events`, внешние ссылки (Grafana/Flower и т.д.). Вход — тот же OAuth/JWT, что у основного API, либо ручная вставка access-токена для отладки. |
| **Admin API** (`server/admin_api/`, отдельный процесс в Docker — сервис **`admin-api`**) | Маршруты под префиксом **`/admin/api/v1/`**: проверка **того же access JWT**, что у основного API, плюс наличие строки в **`admin_memberships`**. Та же БД и Redis; мутации пайплайна идут через общий код постановки Celery. **Содержимое чужих разговоров** (текст транскрипта, аудио) в ответы не попадает — см. **§9** в [docs/ADMIN_OPS_CONSOLE.md](docs/ADMIN_OPS_CONSOLE.md). |
| **Данные** | Таблицы `admin_memberships`, `admin_audit_events`, `auth_signin_events`, `pipeline_events`; прогресс нарезки ASR — колонки `transcripts.asr_chunk_*`. Миграции Alembic в `server/alembic/versions/`. |

Контракт HTTP для админ-маршрутов — в [`openapi.yaml`](openapi.yaml) (тег `admin`). Локальный запуск и переменные — в [`docker/README.md`](docker/README.md) (сервисы **`admin-api`**, **`admin-webui`**, порт **8003** / **3003**, allowlist **`VT_ADMIN_WEBUI_ORIGIN`** на продуктовом **api**).
