# Docker deployment – Voice Transcriber

Run the full speech transcription stack locally with Docker Compose.

**Серверные образы** (`api`, `worker`, `diarization`, `worker-final-gpu`) собираются на **Python 3.12** (`python:3.12-slim`). Локальная разработка `server/` и пересборка `poetry.lock` — тоже на **3.12** (см. [docs/DEPENDENCIES_MIGRATION.md](../docs/DEPENDENCIES_MIGRATION.md)).

## Services

| Service  | Port(s) на хосте | Описание |
|----------|------------------|----------|
| **api**  | **8002**→8000 | FastAPI (см. `ports` в compose) |
| **admin-api** | **8003**→8000 | Отдельный Admin / Ops API ([docs/ADMIN_OPS_CONSOLE.md](../docs/ADMIN_OPS_CONSOLE.md)): тот же JWT, проверка таблицы `admin_memberships` |
| **admin-webui** | **3003**→3000 | Ops-консоль: OAuth через продуктовый **api** (`client=admin`) или JWT вручную; см. [AUTH_AND_IDENTITY.md §8](../docs/AUTH_AND_IDENTITY.md) |
| **webui**| **3002**→3000 | React (Vite build) |
| **worker** | —         | Celery: **`VT_MAIN_WORKER_QUEUES`** по умолчанию **asr_fast**, **asr**, **llm**, **cleanup** |
| **worker-llm** | **`scale_llm`** | Только очередь **llm** (§7.6 summary, embeddings); поднимайте вместе с **`VT_MAIN_WORKER_QUEUES=asr_fast,asr,cleanup`** у **worker**, чтобы не было двух потребителей **llm** |
| **worker-final** | —   | Celery (очередь **asr_final** — тяжелый/финальный ASR по ТЗ §17, CPU) |
| **worker-final-gpu** | **`gpu`** | Celery (**`asr_fast`**, **`asr_final`**, GPU; split-режим) |
| **worker-gpu-unified** | **`gpu-unified`** | Celery (**`asr_fast`**, **`asr_final`**, **`diarization`**, GPU; unified-режим) |
| **diarization-worker** | — | Diarization Celery worker: **CPU**, очередь **diarization** (compose profile `diarization`) |
| **diarization-worker-gpu** | — | Diarization Celery worker: **CUDA** (split-режим, профиль compose **`gpu`**) |
| **migrate** | —        | Однократно: `alembic upgrade head` |
| **tests** | — | **Не** стартует с `up`. Образ **dev** (pytest в слое образа): `docker compose run --rm tests` — см. раздел [Unit tests](#unit-tests-compose-service-tests) |
| **postgres** | 5435→5432 (`POSTGRES_PUBLISH_PORT`) | PostgreSQL 16 |
| **redis**  | 6382→6379 (`REDIS_PUBLISH_PORT`) | Redis 7 |
| **minio**  | 9012→9000, 9013→9001 (`MINIO_*_PUBLISH_PORT`) | MinIO S3 + консоль |

## Имя проекта Compose

В `docker-compose.yml` задано **`name: voice-transcriber`**: префикс контейнеров и именованных томов отличается от других compose-файлов, которые раньше могли использовать имя проекта **`docker`** (например Ragflow: `docker-ragflow-cpu-1` и предупреждение про orphan containers).

При **первом** запуске после смены имени Compose создаст новые тома вида `voice-transcriber_*`. Старые данные в томах `docker_*` к этому проекту не подключаются автоматически; при необходимости перенесите БД дампом или вручную привяжите нужный volume.

## Quick start (Phase A — полный стек)

Из каталога **`docker/`** (имя проекта в compose: **`voice-transcriber`**):

```bash
cd docker
docker compose up --build
```

Порты **на хосте** (см. `docker-compose.yml`):

| Сервис | URL на хосте |
|--------|----------------|
| **Web UI** | http://localhost:**3002** (контейнер слушает 3000) |
| **API** | http://localhost:**8002** (внутри контейнера порт **8000**) |
| **API health** | http://localhost:8002/health |
| **Prometheus metrics** | http://localhost:8002/metrics |
| **WebSocket** | `ws://localhost:8002/ws/audio/{id}`, `ws://localhost:8002/ws/transcript/{id}` — см. [docs/WEBSOCKET.md](../docs/WEBSOCKET.md) |
| **Swagger** | http://localhost:8002/docs |
| **Admin API** | http://localhost:**8003** (`/health`, защищённые маршруты под `/admin/api/v1/…`) |
| **Admin Web UI** | http://localhost:**3003** (минимальная консоль спринта 2; вставка access JWT) |
| **MinIO Console** | http://localhost:**9013** (minioadmin / minioadmin) |
| **MinIO S3 API** | http://localhost:**9012** |

Внутри сети compose сервис **api** обращается к MinIO по **`http://minio:9000`** (не путать с пробросом на хост).

**Зависимости старта:** сервис **`migrate`** выполняет Alembic до запуска **api**; **webui** стартует после **healthy** у **api** (healthcheck по `/health`).

Ручная приёмка Phase A: [docs/PHASE_A_ACCEPTANCE.md](../docs/PHASE_A_ACCEPTANCE.md).

## Admin / Ops API (baseline)

Отдельный сервис **`admin-api`** (порт хоста **8003**→8000 в compose): см. [docs/ADMIN_OPS_CONSOLE.md](../docs/ADMIN_OPS_CONSOLE.md). Использует **тот же** `VT_JWT_SECRET` / конфиг подписи JWT, что и продуктовый **api**; доступ к маршрутам `/admin/api/v1/…` только при наличии строки в таблице **`admin_memberships`**. **S3 / MinIO:** в `docker-compose.yml` для **`admin-api`** заданы те же **`VT_S3_ENDPOINT`**, **`VT_S3_BUCKET`**, **`VT_S3_ACCESS_KEY`**, **`VT_S3_SECRET_KEY`**, что и для **`api`**, и добавлен **`depends_on: minio`** — переопределения через env обрабатываются так же, как у основного API (`server/core/config.py`).

**Первый администратор (bootstrap при миграции):** задайте в `.env` рядом с compose или в окружении сервиса **`migrate`** один из параметров (пользователь уже должен существовать в `users`, например после первого входа через Web UI):

- **`VT_ADMIN_BOOTSTRAP_EMAIL`** — email учётной записи;
- или **`VT_ADMIN_BOOTSTRAP_USER_ID`** — UUID пользователя.

Затем выполните миграции (`docker compose run --rm migrate` или полный `up`). Повторный `upgrade` с тем же email не создаст дубликат (`ON CONFLICT DO NOTHING`).

Проверка без UI: `GET http://localhost:8003/health` (без авторизации); `GET http://localhost:8003/admin/api/v1/me` с заголовком `Authorization: Bearer <access JWT>` выданным основным **api** после входа. Цепочка **admin-webui** (порт **3003**) + **admin-api** (**8003**): откройте консоль — **«Google» / «Яндекс»** ведут на `GET /api/auth/...` продуктового API; после провайдера браузер возвращается на админку с токенами в hash. На сервисе **api** задайте **`VT_ADMIN_WEBUI_ORIGIN`** (или **`VT_ADMIN_WEBUI_ORIGINS`**, через запятую) в том же origin, что и у собранной админки (`VITE_ADMIN_WEBUI_SELF_URL` при сборке образа). Переменная должна попасть **в контейнер api**: compose читает **`deploy/docker/.env`** (на prod — **копия** `/etc/voice-transcriber/voice-transcriber.env`, обновляет `install-or-update.sh`; symlink на `/etc/…` не используйте — на части хостов api падает при старте). Дополнительно: **`docker compose --env-file /etc/voice-transcriber/voice-transcriber.env up -d`**. **`docker compose restart api` не перечитывает env** — нужен **`up -d --force-recreate api`**. Для S3: **внутри compose** — `VT_S3_ENDPOINT=http://minio:9000`; **MinIO на хосте** — `http://host.docker.internal:<порт>` (не `localhost` из контейнера). См. `voice-transcriber.env.example` § S3. **Консоль Google/Яндекс:** redirect/callback остаётся только URL API (`…/api/auth/*/callback`), отдельно регистрировать хост админки не нужно. Ручной ввод JWT по-прежнему возможен. В БД после миграций: в т.ч. **`pipeline_events`**, колонки **`transcripts.asr_chunk_*`** (прогресс нарезки ASR), ранее — `admin_memberships`, `admin_audit_events`, `auth_signin_events` (см. `server/alembic/versions/`).

Переменные окружения сервиса **`admin-api`** (опционально, см. также `configs/server.yaml` → `admin_console`):

| Переменная | Назначение |
|------------|------------|
| **`VT_WEBUI_ORIGIN`** | Базовый URL основного Web UI; если не задан явный шаблон, для карточки разговора подставляется `{VT_WEBUI_ORIGIN}/conversations/{conversation_id}`. |
| **`VT_ADMIN_EXTERNAL_TOOLS_JSON`** | JSON-массив `[{"name":"Flower","url":"http://..."}]` — полностью заменяет список ссылок из YAML для деплоя. |
| **`VT_ADMIN_PRODUCT_CONVERSATION_URL_TEMPLATE`** | Явный шаблон deep-link (должен содержать подстроку `{conversation_id}`). |

## Unit tests (compose service `tests`)

Сервис **`tests`** собирается из `docker/Dockerfile.api` со стадией **`dev`** (`poetry install --with dev`: **pytest** и остальные dev-зависимости зафиксированы в образе, не теряются при пересборке в отличие от ручного `pip install` в контейнере **api**).

Запуск из каталога **`docker/`** (нужны **postgres**, **redis**, **minio** — сервис подтянет их через `depends_on`, миграции через **`migrate`**):

```bash
cd docker
docker compose build tests
docker compose run --rm tests
```

По умолчанию выполняется `pytest tests/unit` (см. `CMD` в Dockerfile, стадия **dev**). Свой набор тестов:

```bash
docker compose run --rm tests python -m pytest tests/unit/test_admin_sprint4.py -q --tb=short
```

Типичный набор **админских** unit-тестов (спринты 2–8):

```bash
docker compose run --rm tests python -m pytest tests/unit/test_admin_api_health.py tests/unit/test_admin_sprint2.py tests/unit/test_admin_sprint3.py tests/unit/test_admin_sprint4.py tests/unit/test_admin_sprint5.py tests/unit/test_admin_sprint7.py tests/unit/test_admin_sprint8.py -q --tb=short
```

Внутри compose доступен хост **`minio:9000`**, поэтому тесты, обращающиеся к S3 через boto3 при импорте воркеров, не падают с ошибкой DNS, как на хосте Windows без Docker.

## Порт Postgres на хосте

Проброс: **`${POSTGRES_PUBLISH_PORT:-5435}:5432`**. Если ошибка `Bind for 0.0.0.0:5435 failed: port is already allocated`, задайте свободный порт, например `POSTGRES_PUBLISH_PORT=5436` перед `docker compose up`.

Для **Alembic с хоста** в `VT_DATABASE_URL` используйте тот же порт, что и в пробросе (по умолчанию **5435**).

## Порт Redis на хосте

Проброс: **`${REDIS_PUBLISH_PORT:-6382}:6379`**. При ошибке `Bind for 0.0.0.0:6382 failed: port is already allocated` задайте свободный порт, например `REDIS_PUBLISH_PORT=6383`. С хоста для отладки подключайтесь к `localhost:<этот порт>`; внутри compose API/worker используют **`redis:6379`** (`VT_REDIS_URL` менять не нужно).

## Порты MinIO на хосте

Проброс задаётся как **`${MINIO_PUBLISH_PORT:-9012}:9000`** и **`${MINIO_CONSOLE_PUBLISH_PORT:-9013}:9001`**. Если при `compose up` ошибка вроде `Bind for 0.0.0.0:9012 failed: port is already allocated`, задайте свободные порты, например:

```bash
set MINIO_PUBLISH_PORT=9102
set MINIO_CONSOLE_PUBLISH_PORT=9103
docker compose up -d
```

(PowerShell: `$env:MINIO_PUBLISH_PORT=9102` и т.д.)

## Configuration

The API and worker use environment variables set in `docker-compose.yml`. You can override them without changing YAML configs:

- `VT_DATABASE_URL` – PostgreSQL connection string  
- `VT_REDIS_URL` – Redis connection string  
- `VT_CELERY_VISIBILITY_TIMEOUT` – секунды видимости сообщения в Redis для Celery (по умолчанию в compose **14400** = 4 ч); должно быть **больше** максимальной длительности задачи `transcribe_file` при `task_acks_late`, иначе возможна повторная доставка задачи (ТЗ §17)
- **`VT_MAIN_WORKER_QUEUES`** — список очередей основного **`worker`** (по умолчанию `asr_fast,asr,llm,cleanup`). Если поднимаете **`worker-llm`** (`--profile scale_llm`), задайте например `VT_MAIN_WORKER_QUEUES=asr_fast,asr,cleanup`, чтобы тяжёлый **llm** обрабатывался только выделенным воркером. **При profile `gpu`** уберите **`asr_fast`** из этого списка (слайсы §17 обрабатывает **`worker-final-gpu`**), например `VT_MAIN_WORKER_QUEUES=asr,cleanup` вместе с **`scale_llm`**.
- **`VT_LLM_WORKER_CONCURRENCY`** — concurrency только для **`worker-llm`** (по умолчанию **2**).
- **`VT_ASR_FINAL_WORKER_QUEUES`** — очереди **`worker-final-gpu`** (по умолчанию **`asr_fast,asr_final`**).
- **`VT_ASR_FINAL_CONCURRENCY`** — параллельность **`worker-final-gpu`** (по умолчанию **2**, для параллельной нарезки §17).
- **`VT_ASR_SLICE_QUEUE`** — очередь Celery для **`transcribe_slice`** (по умолчанию **`asr_fast`**; менять только при нестандартной топологии воркеров).
- `VT_S3_ENDPOINT`, `VT_S3_BUCKET`, `VT_S3_ACCESS_KEY`, `VT_S3_SECRET_KEY` – MinIO/S3 (в `docker-compose.yml` через `${VT_S3_*:-…}`; задайте в `docker/.env` или `/etc/voice-transcriber/voice-transcriber.env` при `compose --env-file`)  
- `VT_ENVIRONMENT` – e.g. `production`
- **`VT_JWT_SECRET`** (опционально) — единый секрет подписи JWT для API и воркера. Если не задан, используется **Google OAuth `client_secret`** из `configs/server.yaml` (см. `server/core/security.py`). Задавайте **одинаковое** значение для **api** и **worker**, иначе токены и шифрование объектов в S3 разъедутся.
- **`VT_ASR_REALTIME_PROVIDER`** / **`VT_ASR_FINAL_PROVIDER`** — отдельные движки realtime и final (см. [`MODEL_CONFIGURATION.md`](../docs/MODEL_CONFIGURATION.md)).
- **`VT_GIGAAM_LONGFORM`** — `1`/`0`: longform-режим GigaAM для файлов длиннее ~25 с (нужен `VT_HF_TOKEN` на GPU-воркере).
- **`VT_ASR_PARALLEL_CHUNKS`**, **`VT_ASR_CHUNK_SECONDS`**, **`VT_ASR_CHUNK_OVERLAP_SECONDS`** — параллельная нарезка длинных файлов: слайсы → **`asr_fast`** (или **`VT_ASR_SLICE_QUEUE`**), merge → **`asr_final`** (ТЗ §17).
- **Semantic search (C2):** см. `configs/embeddings.yaml` (монтируется в контейнер как `/app/configs/embeddings.yaml`).
  - `VT_EMBEDDINGS_ENABLED=1` — включить индексацию и `GET /api/search?mode=semantic`
  - `VT_EMBEDDINGS_PROVIDER=ollama|openai`, `VT_EMBEDDINGS_MODEL=...`
  - `VT_OLLAMA_EMBEDDINGS_URL=http://host.docker.internal:11434` (если Ollama на хосте Windows)
  - `VT_OPENAI_API_KEY` / `OPENAI_API_KEY` — для провайдера openai

The `configs/` directory is mounted read-only into the API and worker. Ensure `configs/server.yaml` exists; Docker env vars override matching values from that file.

Пример `.env` рядом с `docker-compose.yml`:

```env
# Опционально; без этого JWT берётся из смонтированного server.yaml
VT_JWT_SECRET=your-long-random-secret

# Внешний S3 вместо встроенного MinIO (см. docs/RELEASE_BUILD_AND_DEPLOY.md §3.4)
# VT_S3_ENDPOINT=https://storage.yandexcloud.net
# VT_S3_BUCKET=my-voice-transcriber
# VT_S3_ACCESS_KEY=...
# VT_S3_SECRET_KEY=...
```

## First-time setup

### MinIO bucket

При старте API/воркер создают бакет **`voice-transcriber`**, если его ещё нет (`head_bucket` / `create_bucket`). Ручное создание в консоли MinIO нужно только если политика прав запрещает автосоздание.

### Database migrations

При `docker compose up` сервис **`migrate`** (тот же `build`, что и у **`api`**) после готовности Postgres выполняет `python -m alembic upgrade head`. Сервисы **`api`** и **`worker`** ждут успешного завершения миграций (`depends_on: condition: service_completed_successfully`).

Ручной прогон при необходимости:

```bash
docker compose build api
docker compose run --rm migrate
# или: docker compose run --rm api python -m alembic upgrade head
```

Используйте **`python -m alembic`**, а не голый `alembic`: в образе зависимости ставятся через `pip install ... --target`, из‑за этого консольный скрипт `alembic` не попадает в `$PATH`, модуль при этом доступен интерпретатору.

**После изменений в `server/` или `configs/`** пересоберите образы **`api`** и **`migrate`** (одинаковый Dockerfile): `docker compose build api migrate`. Иначе в контейнере останется старый код, а с хоста подмонтируется новый `configs/limits.yaml` — возможна ошибка вида `LimitsConfig.__init__() got an unexpected keyword argument 'allowed_realtime_modes'`.

**Если `migrate` падает с `relation "conversations" does not exist`, а в логе первой идёт ревизия `stage0_001` (а не `initial_001`)** — в образе всё ещё старые файлы `alembic/versions/*`. Выполните **`docker compose build --no-cache migrate api`**, затем снова `docker compose run --rm migrate`.

Цепочка миграций включает **`phase_audio_ext_003`** (`conversations.audio_object_ext` для формата загружаемого аудио).

**Миграции с хоста (Windows / вне Docker):** в `configs/server.yaml` указан хост `postgres`, который с хоста не резолвится. Задайте `VT_DATABASE_URL` с адресом localhost и проброшенным портом (по умолчанию **5435**; см. `POSTGRES_PUBLISH_PORT` в compose), затем выполните `alembic upgrade head` из каталога `server/`. Подробнее: [server/README.md](../server/README.md) (раздел Alembic).

## Building the Web UI for a different API URL

To point the frontend at another API (e.g. in production), pass the URL at build time via **`scripts/release/release.env`** (`VITE_API_BASE_URL` and/or `VT_PUBLIC_API_URL`) and run `scripts/release/build-docker.*`, or export those variables before `docker compose build webui`. Compose подставляет `${VITE_API_BASE_URL:-${VT_PUBLIC_API_URL:-http://localhost:8002}}` в `docker-compose.yml`.

Then rebuild the webui image: `docker compose build webui` (на сборочной машине с полным репозиторием, не из дистрибутива `deploy/`).

**Только OAuth / URL фронта (без PyPI):** образы `webui` и `admin-webui` не качают Python-зависимости. Из корня репозитория с заполненным `scripts/release/release.env`:

```powershell
# Имена с дефисом — в кавычках (иначе PowerShell видит -webui как отдельный параметр):
powershell -File scripts/release/build-docker.ps1 -Services "admin-webui"
powershell -File scripts/release/build-docker.ps1 -Services webui,"admin-webui"
powershell -File scripts/release/build-docker.ps1 -Services webui admin-webui
```

Затем упакуйте tar только для этих образов (см. `package-release.ps1`) или положите их в `docker-images/` вручную через `docker save`.

### Admin Web UI за префиксом `/admin/` (prod)

При сборке задайте **`VITE_ADMIN_WEBUI_BASE_PATH=/admin/`** (см. `scripts/release/release.env`). Контейнер **admin-webui**, как и **webui**, отдаёт статику через **`serve`**.

На **внешнем** nginx (обязательно при префиксе `/admin/`):

- **`location /admin/`** → `proxy_pass http://127.0.0.1:3003/;` — **слэш в конце** `proxy_pass`, чтобы `/admin/assets/foo.js` уходил в контейнер как `/assets/foo.js`;
- **`location /admin/api/`** → порт **8003** (admin-api), **выше** блока `/admin/`, иначе API попадёт в SPA;
- не используйте `try_files` с fallback на `index.html` для путей `…/assets/*.js`.

Пример: [nginx/voicer-reverse-proxy.example.conf](./nginx/voicer-reverse-proxy.example.conf). Симптом ошибки: ответ на `…/admin/assets/*.js` — `text/html`, белый экран.

### Ошибка `files.pythonhosted.org failed` при сборке api/worker

Сборка **api** / **worker** / **migrate** обращается к PyPI. Типичные причины: обрыв сети, DNS, блокировка, корпоративный прокси.

1. Повторите `docker compose build` (кэш pip/poetry ускорит повтор).
2. Проверьте интернет/VPN/DNS в Docker Desktop (Settings → Resources → Network).
3. Зеркало PyPI перед сборкой (PowerShell): `$env:PIP_INDEX_URL = "https://pypi.org/simple"` или зеркало вашей организации; в `release.env`: `PIP_INDEX_URL=...`.
4. Для правки OAuth на prod **не обязательно** пересобирать api/worker, если их образы уже есть на машине — достаточно п. «Только OAuth» выше.

В `Dockerfile.api` / `Dockerfile.worker` используется **`poetry.lock`** (без `rm -f poetry.lock`) и увеличенные таймауты pip/poetry.

### Ошибка `attr.setters has no attribute 'pipe'` / `Cannot install httpx` при `poetry install`

При сборке **ml-base** / **api** / **worker** Poetry обновляет пакеты в system site-packages через pip. Если **`attrs`** оказывается в «полуснятом» состоянии, ломается сам pip (`rich` → `attr.setters.pipe`), и установка падает на `httpx` или другом пакете.

1. Повторите сборку — в Dockerfile перед `poetry install` уже выполняется `pip install --force-reinstall attrs==…` из `poetry.lock`.
2. Если ошибка повторяется: `docker builder prune -f`, затем `docker compose build --no-cache worker-gpu-unified` (или упавший сервис).
3. Очистка кэша BuildKit pip/poetry: `docker buildx prune -f`.

## Final ASR: CPU vs GPU (`worker-final` / `worker-final-gpu`)

| Сервис | Профиль | Очереди Celery | Устройство ASR |
|--------|---------|----------------|----------------|
| **`worker-final`** | — (по умолчанию с `up`) | **`asr_final`** | CPU (`VT_ASR_DEVICE=cpu`) |
| **`worker-final-gpu`** | **`gpu`** | **`asr_fast`**, **`asr_final`** | CUDA (`VT_ASR_DEVICE=cuda`, faster-whisper) |

**Важно:** оба final-воркера слушают **`asr_final`**. При profile **`gpu`** **остановите** **`worker-final`**, иначе Celery раздаст final ASR на CPU:

```bash
docker compose stop worker-final
docker compose --profile gpu up -d worker-final-gpu
```

Сборка только GPU-образов (без пересборки `migrate` из `depends_on`):

```bash
docker compose --profile gpu build --no-deps worker-final-gpu diarization-worker-gpu
```

Параллельная нарезка длинных upload (§17) ставит **`transcribe_slice`** в **`asr_fast`**. На GPU-деплое **`worker-final-gpu`** должен быть **единственным** потребителем **`asr_fast`** для тяжёлого ASR — задайте у основного **`worker`**:

```env
VT_MAIN_WORKER_QUEUES=asr,cleanup
```

(если поднят **`worker-llm`** / profile **`scale_llm`**; иначе добавьте **`llm`** в список).

`install-or-update.sh` при **`VT_COMPOSE_PROFILES=…,gpu`** автоматически останавливает **`worker-final`** и **`diarization-worker`** и предупреждает, если **`asr_fast`** остался у основного worker.

Пример prod с GPU:

```env
VT_COMPOSE_PROFILES=gpu,diarization,scale_llm
VT_MAIN_WORKER_QUEUES=asr,cleanup
VT_ASR_DEVICE=cuda
VT_ASR_COMPUTE_TYPE=float16
VT_DIARIZATION_DEVICE=cuda
```

## GPU deployment modes: split vs unified

На GPU-ноде тяжёлые ML-задачи можно развернуть в двух режимах (взаимоисключающих):

| Режим | Сервисы | Очереди Celery | Когда выбирать |
|-------|---------|----------------|----------------|
| **split** (по умолчанию) | `worker-final-gpu` + `diarization-worker-gpu` | `asr_fast`, `asr_final` / `diarization` | Независимый перезапуск, diarization на отдельной VM, разное масштабирование |
| **unified** | `worker-gpu-unified` | `asr_fast`, `asr_final`, `diarization` | Одна GPU, меньше дублирования VRAM, проще ops |

**split:** не запускайте CPU- и GPU-варианты одной очереди одновременно (`worker-final` vs `worker-final-gpu`, `diarization-worker` vs `diarization-worker-gpu`) — см. разделы ниже.

**unified:** один Celery-процесс на **`ml-base-cuda`**, volume **`gpu-ml-models:/models`**. Профиль compose **`gpu-unified`**. `install-or-update.sh` при **`VT_GPU_DEPLOY_MODE=unified`** подставляет `gpu-unified` вместо `gpu` и останавливает split-воркеры.

```bash
cd docker
# unified (одна GPU)
docker compose stop worker-final-gpu diarization-worker-gpu 2>/dev/null || true
docker compose --profile gpu-unified up -d --build worker-gpu-unified

# split (по умолчанию)
docker compose stop worker-gpu-unified 2>/dev/null || true
docker compose --profile gpu up -d --build worker-final-gpu diarization-worker-gpu
```

Prod env (`/etc/voice-transcriber/voice-transcriber.env`):

```env
# unified
VT_GPU_DEPLOY_MODE=unified
VT_COMPOSE_PROFILES=gpu-unified,scale_llm
VT_MAIN_WORKER_QUEUES=asr,cleanup
VT_GPU_UNIFIED_CONCURRENCY=2

# split (альтернатива)
# VT_GPU_DEPLOY_MODE=split
# VT_COMPOSE_PROFILES=gpu,scale_llm
```

Systemd (опционально): `docker/systemd/voice-transcriber-worker-gpu-unified.service`.

**VRAM:** два split-контейнера на **одной** карте могут конкурировать за память (`nvidia-smi` перед выбором режима). Unified снижает дублирование загрузки моделей в RAM/VRAM, но не убирает пиковую нагрузку при параллельных задачах — настройте `VT_GPU_UNIFIED_CONCURRENCY` / `VT_ASR_FINAL_CONCURRENCY`.

### API realtime на GPU (профиль `api-gpu`, R5)

По умолчанию **`api`** — CPU realtime (`VT_ASR_REALTIME_DEVICE=cpu`). Для CUDA faster-whisper в том же контейнере:

```bash
cd docker
docker compose -f docker-compose.yml -f compose.api-gpu.override.yml up -d --build api
```

В `.env`: `VT_ASR_REALTIME_DEVICE=cuda`, при необходимости `VT_ASR_REALTIME_MODEL=small`. Образ `Dockerfile.api` уже включает pip `nvidia-*` и `LD_LIBRARY_PATH`.

**VRAM на одной карте:** `api` (whisper small/medium) + `worker-gpu-unified` (GigaAM final) + при необходимости vLLM — смотрите `nvidia-smi` до включения realtime CUDA; при нехватке памяти оставьте realtime на CPU или уменьшите модель (`VT_ASR_REALTIME_MODEL`).

**Дублирование образов на диске:** split и unified строятся из **`Dockerfile.ml-base`** (`ml-base-cuda`); слои torch общие. См. [DEPENDENCIES.md](../docs/DEPENDENCIES.md#docker-образы-и-дублирование-слоёв).

## Diarization: CPU vs CUDA images

Образы diarization и **`worker-final-gpu`** строятся поверх общего **ML base** ([`Dockerfile.ml-base`](Dockerfile.ml-base), фаза 5b в [DEPENDENCIES_MIGRATION.md](../docs/DEPENDENCIES_MIGRATION.md)):

| Child-сервис | ML base | Torch |
|--------------|---------|-------|
| **`diarization-worker`** | `ml-base-cpu` | CPU (`whl/cpu`) |
| **`diarization-worker-gpu`** | `ml-base-cuda` | CUDA (`whl/cu128`) |
| **`worker-final-gpu`** | `ml-base-cuda` | CUDA (тот же слой, что у diarization GPU) |

Сборка base (при смене `poetry.lock` / torch):

```bash
cd docker
docker compose --profile ml-base build ml-base-cpu ml-base-cuda
```

Child-образы в compose собираются **targets** в том же `Dockerfile.ml-base` (`diarization-worker`, `worker-final-gpu`, …) — BuildKit переиспользует стадии `ml-base-*` без отдельного `depends_on`. Для registry с предзагруженным base: тонкие [`Dockerfile.diarization`](Dockerfile.diarization) / [`Dockerfile.worker.gpu`](Dockerfile.worker.gpu) с `ARG ML_BASE_IMAGE`.

В `docker-compose.yml`:

- Сервис **`diarization-worker`** — `ML_BASE_IMAGE: voice-transcriber-ml-base-cpu:…`, **профиль `diarization`**. Поднимается явно: `docker compose --profile diarization up -d --build diarization-worker`.
- Сервис **`diarization-worker-gpu`** — `ML_BASE_IMAGE: voice-transcriber-ml-base-cuda:…`, профиль **`gpu`**. Поднимается явно: `docker compose --profile gpu up -d …`.

**Важно:** оба воркера слушают одну и ту же очередь Celery **`diarization`**. Не запускайте CPU и GPU воркеры одновременно, если не хотите дублировать обработку одной и той же очереди. Обычно в проде активен **ровно один** diarization-сервис.

**Сборка и сеть:** **ml-base** и CUDA child-образы качают PyTorch и колёса **`nvidia-*`** (сотни МБ). Первая сборка **ml-base-cuda** — **десятки минут**; не уводите ПК в сон. При таймауте перезапустите только упавший сервис: `docker compose --profile ml-base build ml-base-cuda` или `docker compose --profile gpu build worker-final-gpu`. Кэш слоёв Docker и pip (`--mount=type=cache`) сохраняют уже собранное. После готового base пересборка child при правках только `server/` — быстрая. `pip-retry.sh`, `PIP_DEFAULT_TIMEOUT=1800`.

### Первое развёртывание: какой сервис выбрать

**Только CPU (рекомендуется по умолчанию, dev, машины без NVIDIA в Docker):**

```bash
cd docker
docker compose up -d --build
```

**Включить diarization-worker дополнительно (профиль `diarization`):**

```bash
cd docker
docker compose --profile diarization up -d --build diarization-worker
```

Убедитесь, что **`diarization-worker-gpu` не запущен** (он в профиле `gpu` и сам по себе не стартует без `--profile gpu`).

**GPU / CUDA (Linux или WSL2 с NVIDIA Container Toolkit):**

```bash
cd docker
# не поднимайте CPU diarization-worker параллельно с GPU-вариантом
docker compose stop diarization-worker
docker compose --profile gpu up -d --build diarization-worker-gpu
```

В `configs/diarization.yaml` для GPU обычно задают `device: cuda` или `device: auto` (см. комментарии в YAML). Выбор **wheels CPU vs CUDA** — только build-arg / отдельный compose-сервис, не этот файл.

### Diarization: повторный ASR по turn vs только спикеры

- В **`configs/diarization.yaml`** поле **`turn_level_retranscription`**: при **`false`** (дефолт в репозитории) задача diarization **не** вызывает ASR заново на коротких клипах по каждому turn pyannote — только **расстановка спикеров** по уже готовому тексту batch ASR; при **`true`** (и наличии ASR + **ffmpeg** в образе воркера) допускается **turn-level re-ASR** (текст может измениться).
- Переопределение без правки YAML на старте процесса: переменная окружения **`VT_DIARIZATION_TURN_LEVEL_RETRANSCRIPTION`** (`true` / `false` / `1` / `0` / `yes` / `on` — см. `server/core/config.py`). Задайте её для **api** и **diarization-worker** (и при необходимости **worker**), если хотите единое значение во всём стеке, читающем общий конфиг.
- Пользовательский override в **Web UI → Settings** (`GET/PATCH /api/settings/user`, поля `diarization_turn_level_retranscription_*`); серверный дефолт для подсказки в форме — **`diarization_turn_level_retranscription_default`** в **`GET /api/settings/limits`**. **Расширение Chromium эти настройки не дублирует.**
- Повторить **полный batch ASR** по уже загруженному аудио: **`POST /api/conversations/{id}/retranscribe`** или кнопка **Transcribe again** в Web UI (очередь и задача те же, что после **`POST /api/upload`**).

### Как сменить вариант после первого развёртывания

1. **Остановить** текущий diarization-воркер (чтобы не было двух потребителей очереди):

   ```bash
   docker compose stop diarization-worker
   # или, если использовали GPU:
   docker compose --profile gpu stop diarization-worker-gpu
   ```

2. **Пересобрать** нужный образ (после смены `DIARIZATION_TORCH` или обновления lock):

   ```bash
   docker compose build diarization-worker
   # или:
   docker compose --profile gpu build diarization-worker-gpu
   ```

3. **Запустить** другой сервис и при необходимости поправить `device` в `configs/diarization.yaml`, затем:

   ```bash
   docker compose up -d diarization-worker
   # или с GPU:
   docker compose --profile gpu up -d diarization-worker-gpu
   ```

4. При смене **только** `configs/diarization.yaml` достаточно `docker compose restart <имя-сервиса>`.

Переопределение build-arg без правки YAML (например в CI):

```bash
docker compose build --build-arg DIARIZATION_TORCH=cuda diarization-worker-gpu
```

(Сервис `diarization-worker-gpu` уже задаёт `cuda` в `docker-compose.yml`; аргумент нужен только если переопределяете образ вручную.)

## Diarization: offline models (pyannote) — прогрев кэша

Полная таблица «что с Hugging Face для локальной работы» (ASR, diarization, GigaAM, токен, чеклист offline): **[docs/OFFLINE_AND_HUGGINGFACE.md](../docs/OFFLINE_AND_HUGGINGFACE.md)**.

Если `configs/diarization.yaml` содержит `offline_models: true`, diarization-воркер **не будет скачивать** модели из сети
(`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`). В этом режиме модели должны быть заранее доступны в каталоге кэша
(`model_cache_dir`, по умолчанию `/models`, примонтирован как volume `diarization-models`).

### Быстрый прогрев (один раз) в online-режиме

1) Временно включите online режим:

- `configs/diarization.yaml`: `offline_models: false`
- Задайте токен: `VT_HF_TOKEN` (HuggingFace) в окружении/`.env` рядом с `docker-compose.yml`

2) Поднимите diarization-воркер и прогрейте кэш (см. также [OFFLINE_AND_HUGGINGFACE.md](../docs/OFFLINE_AND_HUGGINGFACE.md)):

```bash
docker compose --profile diarization up -d diarization-worker
```

3) Прогрейте кэш **без разговора** (рекомендуется):

```bash
docker compose --profile diarization run --rm diarization-worker python -m app.diarization.warmup
```

Альтернатива: запустить diarization на любом разговоре (через Web UI **Diarize again** или API `POST /api/conversations/{id}/diarize`), либо повторить только ASR (**Transcribe again** / `POST /api/conversations/{id}/retranscribe`).

4) Переключите в offline:

- `configs/diarization.yaml`: `offline_models: true`
- Можно убрать `VT_HF_TOKEN` (если модели уже локально и доступ не нужен)

5) Перезапустите воркер:

```bash
docker compose restart diarization-worker
```

Примечание: если в offline-режиме кэш пустой/неполный, задача diarization завершится ошибкой, а активная версия транскрипта
не изменится (будет создана новая версия со статусом `failed`).

### Self-check при старте воркера

В образе diarization-воркера предусмотрен опциональный startup self-check (warmup), включаемый переменной:

- `VT_DIARIZATION_WARMUP=1` — перед стартом Celery выполняется `python -m app.diarization.warmup`

Если warmup падает (например offline mode + пустой кэш), воркер не стартует — это удобнее, чем ловить ошибки на первых job’ах.

## Diarization GPU (Linux / WSL2)

GPU-воркер — сервис **`diarization-worker-gpu`** (профиль **`gpu`**), образ собирается с **`DIARIZATION_TORCH=cuda`**. Подробнее и как не смешивать с CPU-воркером: раздел **[Diarization: CPU vs CUDA images](#diarization-cpu-vs-cuda-images)** выше.

Запуск (Linux или WSL2 с настроенным NVIDIA Container Toolkit), после остановки CPU-воркера при необходимости:

```bash
docker compose stop diarization-worker
docker compose --profile gpu up -d --build diarization-worker-gpu
```

Требования:

- Хост Linux: установлен NVIDIA driver + NVIDIA Container Toolkit
- WSL2: настроена поддержка CUDA в WSL и Docker Desktop/Engine с NVIDIA runtime

Если GPU недоступен, используйте **`diarization-worker`** (CPU wheels) и `device: auto|cpu` в `configs/diarization.yaml`.

### Troubleshooting GPU

Быстрая диагностика:

- **Контейнер видит GPU?**

```bash
docker compose --profile gpu exec diarization-worker-gpu nvidia-smi
```

Если `nvidia-smi` не найден или падает — проблема на уровне хоста/контейнерного рантайма (не в приложении).

- **PyTorch видит CUDA?**

```bash
docker compose --profile gpu exec diarization-worker-gpu python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')"
```

Типовые причины, если `torch.cuda.is_available()` возвращает `False`:

- **Не установлен NVIDIA Container Toolkit** (Linux) или не настроен runtime.
- **WSL2**: отсутствует/не включена CUDA поддержка в WSL, или Docker Desktop не использует NVIDIA runtime.
- **Драйвер**: слишком старый/несовместимый с используемой версией CUDA/Torch.

Полезная проверка на хосте:

```bash
nvidia-smi
```

Если на хосте `nvidia-smi` не работает, контейнер тоже не сможет использовать GPU.

## Volumes

- `postgres-data` – PostgreSQL data  
- `redis-data` – Redis data  
- `minio-data` – MinIO object storage  
- `diarization-models` – кэш моделей HuggingFace/pyannote (для offline/online режимов)  

Server logs are written to `../server/logs` (mounted from the host).

## Commands

```bash
# Start in background
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down

# Stop and remove volumes
docker compose down -v
```

## Production (VM + systemd): diarization worker as separate service

Если вы хотите запускать diarization на отдельной VM (или просто как отдельный systemd unit), используйте шаблон:

- `docker/systemd/voice-transcriber-diarization-worker.service`
- `docker/systemd/voice-transcriber-diarization-worker-gpu.service`
- `docker/systemd/voice-transcriber-api-worker.service`
- `docker/systemd/voice-transcriber-stack.service`
- `docker/systemd/voice-transcriber.env.example`

Рекомендуемая схема:

- **VM A**: `api` + `worker` + `migrate` + инфраструктура (`postgres`, `redis`, `minio`) или подключение к внешним managed-сервисам.
- **VM B**: только `diarization-worker` (профиль `diarization`), который подключается к тем же `VT_DATABASE_URL`, `VT_REDIS_URL`, `VT_S3_*`.

Альтернатива для VM A:

- Если хотите запускать **весь compose-стек** одним unit (включая `postgres/redis/minio`): используйте `voice-transcriber-stack.service`.
- Если инфраструктура внешняя (managed Postgres/Redis/S3): используйте `voice-transcriber-api-worker.service` и переопределите `VT_DATABASE_URL`, `VT_REDIS_URL`, `VT_S3_*` через `/etc/voice-transcriber/voice-transcriber.env`.

### Установка unit файла

1) Скопируйте unit:

```bash
sudo install -m 0644 /opt/voice-transcriber/docker/systemd/voice-transcriber-diarization-worker.service \
  /etc/systemd/system/voice-transcriber-diarization-worker.service
```

GPU-вариант (если diarization VM с NVIDIA и вы используете сервис `diarization-worker-gpu`, compose profile `gpu`):

```bash
sudo install -m 0644 /opt/voice-transcriber/docker/systemd/voice-transcriber-diarization-worker-gpu.service \
  /etc/systemd/system/voice-transcriber-diarization-worker-gpu.service
```

Для VM A выберите один из unit’ов:

```bash
sudo install -m 0644 /opt/voice-transcriber/docker/systemd/voice-transcriber-stack.service \
  /etc/systemd/system/voice-transcriber-stack.service

# или (только migrate+api+worker+webui):
sudo install -m 0644 /opt/voice-transcriber/docker/systemd/voice-transcriber-api-worker.service \
  /etc/systemd/system/voice-transcriber-api-worker.service
```

2) (Опционально) env overrides:

```bash
sudo install -d /etc/voice-transcriber
sudo cp /opt/voice-transcriber/docker/systemd/voice-transcriber.env.example /etc/voice-transcriber/voice-transcriber.env
sudo nano /etc/voice-transcriber/voice-transcriber.env
```

3) Включите и запустите:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now voice-transcriber-diarization-worker.service
```

Для GPU diarization:

```bash
sudo systemctl enable --now voice-transcriber-diarization-worker-gpu.service
```

Для VM A:

```bash
sudo systemctl enable --now voice-transcriber-stack.service
# или:
sudo systemctl enable --now voice-transcriber-api-worker.service
```

4) Логи:

```bash
journalctl -u voice-transcriber-diarization-worker.service -f
```

GPU:

```bash
journalctl -u voice-transcriber-diarization-worker-gpu.service -f
```

Для VM A:

```bash
journalctl -u voice-transcriber-stack.service -f
# или:
journalctl -u voice-transcriber-api-worker.service -f
```

### Важно

- Unit использует `docker compose --profile diarization ...`. Убедитесь, что на VM установлен Docker Engine/Compose v2.
- `WorkingDirectory` в unit сейчас задан как `/opt/voice-transcriber/docker`. Если у вас другой путь — измените его в `.service`.
- Для online загрузки pyannote моделей задайте `VT_HF_TOKEN` (и убедитесь, что volume `/models` сохраняется/примонтирован как в compose).
- GPU unit использует `docker compose --profile gpu ...`. Для этого на хосте должны быть NVIDIA драйвер и NVIDIA Container Toolkit, и контейнер должен видеть GPU (см. раздел **Diarization GPU (Linux / WSL2)** выше).
- В `voice-transcriber-diarization-worker-gpu.service` есть `ExecStartPre=/usr/bin/nvidia-smi` — это **guard**, чтобы сервис падал сразу, если GPU на хосте не настроен.
