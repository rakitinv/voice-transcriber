## Server (Backend) Skeleton

This directory contains the **backend skeleton** for the voice transcription system.

### Tech stack

- **Language**: Python
- **Web framework**: FastAPI
- **Task queue**: Celery
- **Broker**: Redis
- **Database**: PostgreSQL
- **Object storage**: S3-compatible (MinIO)

### Planned responsibilities

- OAuth2 authentication (Google, Yandex).
- Realtime transcription via WebSocket.
- Batch transcription via file upload.
- Multi-thread / chunked transcription for long audio.
- Speaker diarization (post-processing only).
- LLM-based conversation summaries.
- Transcript and embeddings search (PostgreSQL full-text + semantic).
- Per-user encrypted storage and TTL cleanup.

### Current layout (skeleton)

- `app/` – FastAPI app package and API routers.
- `workers/` – Celery workers for ASR, diarization, and LLM.
- `config/` – Server-side configuration loading and models.
- `core/` – Security, database, S3, logging, and utilities.
- `plugins/` – Pluggable ASR, diarization, and LLM providers.
- `migrations/` – Database migrations (e.g. Alembic).
- `tests/` – Backend tests (e.g. Phase A e2e, см. `tests/` и `docs/TESTING.md`).

### JWT

Подпись и проверка access token: **`VT_JWT_SECRET`** (рекомендуется в Docker/prod для API и worker одинаково). Если не задан — используется **Google OAuth `client_secret`** из `configs/server.yaml`. См. `core/security.py`.

### Alembic (миграции БД)

`configs/server.yaml` задаёт хост БД **`postgres`** — это имя сервиса в Docker. Команда `alembic upgrade head` **на вашей машине** без `VT_DATABASE_URL` будет пытаться резолвить `postgres` и завершится ошибкой вроде `could not translate host name "postgres"`.

**Вариант A — Postgres уже запущен через `docker compose` из каталога `docker/`**  
На хост пробрасывается порт **`POSTGRES_PUBLISH_PORT`** (в compose по умолчанию **5435** → 5432 в контейнере). Если меняли переменную — подставьте свой порт. В PowerShell из каталога `server/`:

```powershell
$env:VT_DATABASE_URL = "postgresql+psycopg2://voice:voice@127.0.0.1:5435/voice"
.\.venv\Scripts\activate
alembic upgrade head
```

**Вариант B — миграции внутри контейнера API** (хост `postgres` доступен):

```bash
cd docker
docker compose run --rm api python -m alembic -c /app/server/alembic.ini upgrade head
```

Только для Alembic можно вместо `VT_DATABASE_URL` задать **`ALEMBIC_DATABASE_URL`** (см. `alembic/env.py`).

После обновления кода выполните **`alembic upgrade head`**: цепочка **`initial_001`** → **`stage0_001`** → **`phase_a_002`** → **`phase_audio_ext_003`** (`audio_object_ext` на `conversations`; `stage0`/`phase_a` идемпотентны при совпадении схемы с моделями).

