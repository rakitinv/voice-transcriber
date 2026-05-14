# Сборка release-артефактов и развёртывание на площадке

Документ описывает, как получить **production-сборки** компонентов репозитория Voice Transcriber для выката на целевую среду. Целевой способ эксплуатации в этом документе — **Docker Compose на одной или нескольких ВМ** (или эквивалент «docker stack» без Kubernetes). **Kubernetes и Helm** здесь не рассматриваются.

Детали по переменным окружения, портам и профилям Docker: [docker/README.md](../docker/README.md). OAuth и идентичность: [AUTH_AND_IDENTITY.md](./AUTH_AND_IDENTITY.md), Ops-консоль: [ADMIN_OPS_CONSOLE.md](./ADMIN_OPS_CONSOLE.md).

Автоматизация рутины: в корне репозитория есть **[Makefile](../Makefile)**; в CI — workflow [.github/workflows/release-artifacts.yml](../.github/workflows/release-artifacts.yml) (сборка wheel/sdist CLI и каталога `browser-extension/dist/`).

---

## 1. Состав продукта (что именно собирать)

| Компонент | Каталог / образ | Назначение |
|-----------|-----------------|------------|
| API | `docker/Dockerfile.api` (стадия **runtime**) | Основной FastAPI, WebSocket, OAuth |
| Admin API | тот же образ, другая команда `uvicorn` | Маршруты `/admin/api/v1/…` |
| Миграции БД | тот же образ, однократный `alembic upgrade head` | Сервис `migrate` в compose |
| Celery worker (основной) | `docker/Dockerfile.worker` | Очереди `asr_fast`, `asr`, `llm`, `cleanup` (настраивается) |
| Celery worker (финальный ASR) | `docker/Dockerfile.worker` | Очередь `asr_final` |
| Celery worker (финальный ASR, GPU) | `docker/Dockerfile.worker.gpu` | Профиль compose `gpu` |
| Diarization worker | `docker/Dockerfile.diarization` | Профиль `diarization` или `gpu` |
| Web UI (пользовательский SPA) | `docker/Dockerfile.webui` | Статическая сборка Vite + контейнер **`serve`** |
| Admin Web UI (Ops-консоль) | `docker/Dockerfile.admin-webui` | Отдельный SPA + **`serve`** |
| Инфраструктура (опционально в одном compose) | сервисы **`postgres`**, **`redis`**, **`minio`** | БД, брокер, S3-совместимое хранилище |
| Конфигурация | `configs/*.yaml` | Монтируется read-only; env переопределяет значения |
| CLI | `cli/` (Python package) | Команда `transcriber`, дистрибутив wheel/sdist |
| Расширение браузера | `browser-extension/` | MV3 Chromium, каталог `dist/` |

На площадке обычно публикуют **Docker-образы** в registry и/или **дополнительные артефакты** (wheel CLI, zip расширения). Ниже — каноничные команды сборки из исходников.

---

## 2. Общие требования к среде сборки

- **Docker** с BuildKit, **Docker Compose** v2.
- Для образов с Node: в Dockerfiles зафиксирован **Node 22** (`Dockerfile.webui`, `Dockerfile.admin-webui`).
- Для API/worker: **Python 3.11** в образе (`Dockerfile.api`).
- Доступ в интернет на этапе `docker build` / `npm ci` / `poetry install` (или кэши и корпоративный proxy).

Рекомендация: зафиксировать **тег git** (semver или дата плюс SHA) и проставить его же в registry и в именах артефактов (CLI, zip расширения).

### 2.1. Что имелось в виду под «отдельным артефактом для фронтов»

Сейчас в репозитории **Web UI** и **Admin Web UI** собираются **внутри Docker-образа**: в образ попадает уже готовый `dist/` плюс лёгкий сервер статики **`serve`** (Node в runtime).

Под **отдельным артефактом фронтов** имелась в виду **только папка статики** после `npm run build` (каталоги `webui/dist/` и `admin-webui/dist/`), **без** образа с Node:

- вы собираете SPA на CI или на машине (`cd webui && npm ci && npm run build`);
- выкладываете содержимое `dist/` на **nginx, Caddy, S3 static website, CDN** и т.п.;
- обратный прокси отдаёт `index.html` и ассеты, а API остаётся на другом хосте.

Плюсы: меньше поверхность в runtime, привычный паттерн для prod. Минусы: нужно самим настроить SPA fallback (`try_files` для React Router), заголовки кэша и TLS. Текущие Dockerfiles с `serve` — допустимый и простой вариант для внутренних стендов; для жёсткого prod часто переходят на «только статика». В обоих случаях **`VITE_*`** задаются **на этапе сборки** (`docker build` или `npm run build`).

---

## 3. Серверные компоненты (Docker)

### 3.1. Сборка всех сервисов из compose

Из каталога **`docker/`** (имя проекта в compose: **`voice-transcriber`**):

```bash
cd docker
docker compose build
```

Сервисы с **профилями** по умолчанию не стартуют при `up`, но образы можно собрать явно:

```bash
docker compose build worker-llm worker-final-gpu diarization-worker diarization-worker-gpu
docker compose --profile scale_llm --profile gpu --profile diarization build
```

См. [docker/README.md](../docker/README.md).

Из корня репозитория (если установлен **make**):

```bash
make docker-build
```

### 3.2. Публикация образов в registry

После сборки присвойте теги и выполните `docker push` (подставьте `REGISTRY`, `PROJECT`, `TAG`):

```bash
docker tag voice-transcriber-api:latest REGISTRY/PROJECT/vt-api:TAG
docker push REGISTRY/PROJECT/vt-api:TAG
```

Имена локальных образов смотрите: `docker images` (префикс `voice-transcriber`).

**SBOM и скан уязвимостей** перед выкатом на prod (пример, подставьте тег образа):

```bash
docker scout quickview REGISTRY/PROJECT/vt-api:TAG
# или: trivy image REGISTRY/PROJECT/vt-api:TAG
```

### 3.3. Критичные параметры на этапе сборки фронтов

**Web UI:** build-arg **`VITE_API_BASE_URL`** (`docker/Dockerfile.webui`, сервис `webui` в compose). Для prod — публичный HTTPS URL API до `docker compose build webui`.

**Admin Web UI** (`docker/Dockerfile.admin-webui`, сервис `admin-webui`):

- **`VITE_ADMIN_API_BASE_URL`** — URL Admin API с точки зрения браузера.
- **`VITE_PUBLIC_API_BASE_URL`** — URL основного API (OAuth, refresh).
- **`VITE_ADMIN_WEBUI_SELF_URL`** — origin админки; должен совпадать с **`VT_ADMIN_WEBUI_ORIGIN`** / **`VT_ADMIN_WEBUI_ORIGINS`** на сервисе **api**.

Подробнее: [ADMIN_OPS_CONSOLE.md](./ADMIN_OPS_CONSOLE.md).

### 3.4. Варианты развёртывания: Postgres и S3

Общие правила:

- Переменные **`VT_DATABASE_URL`**, **`VT_S3_ENDPOINT`**, **`VT_S3_BUCKET`**, **`VT_S3_ACCESS_KEY`**, **`VT_S3_SECRET_KEY`** переопределяют значения из `configs/` (см. [server/core/config.py](../server/core/config.py)).
- **`VT_JWT_SECRET`** одинаковый для **api**, **admin-api**, всех **worker**, иначе JWT и шифрование объектов в S3 разъедутся.
- Каталог **`configs/`** монтируется read-only; для prod подготовьте YAML с реальными OAuth и лимитами или полностью опирайтесь на env.

#### Вариант A: «свои» PostgreSQL и S3-совместимый MinIO в том же compose

Штатный [docker/docker-compose.yml](../docker/docker-compose.yml): сервисы **`postgres`**, **`redis`**, **`minio`** поднимаются вместе с приложением; строки подключения указывают на хосты **`postgres`** и **`minio`** внутри сети compose.

Подходит для площадки, где допустимо хранить данные на дисках ВМ и управлять бэкапами самостоятельно. Не публикуйте порты Postgres/MinIO в интернет без TLS и firewall.

#### Вариант B: внешняя управляемая PostgreSQL и/или внешний S3 (AWS, Yandex Object Storage, Ceph и т.д.)

Задайте в **`docker/.env`** (или в окружении перед `docker compose up`) реальные значения, например:

```env
# PostgreSQL (хост и порт должны быть достижимы ИЗ контейнеров; для БД на хосте Windows/Mac часто host.docker.internal)
VT_DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@db.example.com:5432/voice?sslmode=require

VT_S3_ENDPOINT=https://s3.amazonaws.com
VT_S3_BUCKET=my-company-voice-transcriber
VT_S3_ACCESS_KEY=...
VT_S3_SECRET_KEY=...
```

Для провайдеров с отдельным **региональным endpoint** подставьте полный URL в **`VT_S3_ENDPOINT`**, как требует ваш облачный S3.

**Сеть и безопасность:** из контейнеров `api` / `worker` / `migrate` должен быть разрешён исходящий трафик к хосту БД и к endpoint S3 (security groups, корпоративный firewall, TLS).

**Важно про штатный compose:** сервисы приложения объявляют **`depends_on: postgres`** и **`minio`**. Если вы **только переопределяете** `VT_*` через `.env`, локальные **`postgres`** и **`minio`** всё равно могут подниматься (приложение к ним не подключается, если URL указывают наружу). Это лишние ресурсы и порты; для чистого prod обычно делают **сайт-специфичную копию** `docker-compose.yml` или **дополнительный compose-файл**, где сервисы `postgres` и/или `minio` удалены, а `depends_on` на них убраны у `migrate`, `api`, `worker`, `admin-api` и т.д. (структура зависит от вашей политики merge compose на площадке).

**Миграции:** сервис **`migrate`** должен выполняться с тем же **`VT_DATABASE_URL`**, что и рабочий API, чтобы Alembic применился к правильной базе.

**Redis** в текущем стеке по-прежнему нужен как брокер Celery и для части функций API; его чаще оставляют в compose. Вынести Redis во внешний managed-сервис можно аналогично через **`VT_REDIS_URL`**, сняв сервис `redis` из compose на сайт-специфичной конфигурации.

### 3.5. Конфигурация и секреты (кратко)

- OAuth client id/secret: `configs/server.yaml` или переменные окружения по [docker/README.md](../docker/README.md).
- Проброс портов Postgres/Redis/MinIO в штатном compose удобен для отладки; на prod с внешними сервисами наружу обычно торчат только **API**, **Web UI**, **Admin Web UI** (и при необходимости Redis только во внутренней сети).

### 3.6. Миграции перед запуском приложения

Сервис **`migrate`** в compose выполняет `python -m alembic upgrade head` до старта API. Порядок на площадке: **сначала миграции**, затем API и воркеры. Внутри образа используйте **`python -m alembic`**, не бинарь `alembic` в PATH (см. [docker/README.md](../docker/README.md)).

### 3.7. Запуск сервера без Docker (кратко)

Возможен выкат на ВМ с Python 3.11 и Poetry (`poetry install --only main`), отдельные процессы uvicorn и Celery. Системные зависимости (ffmpeg и др.) нужно воспроизвести вручную по образцу `Dockerfile.api`. Для площадок с Compose этот путь обычно не нужен.

---

## 4. CLI (клиент `transcriber`)

Пакет **`voice-transcriber-cli`**: [cli/README.md](../cli/README.md), [cli/pyproject.toml](../cli/pyproject.toml).

### 4.1. Сборка дистрибутива (wheel и sdist)

```bash
cd cli
python -m pip install --upgrade pip build
python -m build
```

Артефакты: **`cli/dist/`**. Или: `make release-cli` из корня репозитория.

### 4.2. Установка на рабочей станции

```bash
cd cli
pip install .
```

Для разработки: `pip install -e .`.

### 4.3. Настройка на площадке использования

- **`VT_API_BASE_URL`** / **`--base-url`** — публичный URL API.
- **`VT_ACCESS_TOKEN`** или **`VT_API_KEY`** — см. [cli/README.md](../cli/README.md).

Совместимость с развёрнутым API: [openapi.yaml](../openapi.yaml). Рекомендуется вести **changelog** или semver API при ломающих изменениях контракта.

---

## 5. Расширение браузера (Chromium, MV3)

### 5.1. Production-сборка

```bash
cd browser-extension
npm ci
npm run build
```

Или: `make release-extension` из корня.

Результат: **`browser-extension/dist/`** — загрузка как **распакованное расширение** в `chrome://extensions` (режим разработчика). См. [browser-extension/README.md](../browser-extension/README.md).

Публикация в **Chrome Web Store** в рамках текущего документа **не требуется**; для корпоративного распространения достаточно zip каталога `dist/` или внутреннего портала политик.

### 5.2. Пакет для передачи пользователям

Заархивируйте **содержимое** `dist/` в `voice-transcriber-extension-<версия>.zip`. Версию в **`manifest.json`** синхронизируйте с сервером при изменении OAuth или WebSocket.

### 5.3. Соответствие серверу

Базовый URL API и OAuth: см. [AUTH_AND_IDENTITY.md](./AUTH_AND_IDENTITY.md); redirect URI в консоли провайдера — на **продуктовый API**, не на статику фронта.

---

## 6. Минимальный чеклист перед выкатом

1. Один тег версии на git и на образы/артефакты.
2. Пересборка **webui** и **admin-webui** с корректными **`VITE_*`**.
3. Согласованные **`VT_JWT_SECRET`**, **`VT_DATABASE_URL`**, **`VT_REDIS_URL`**, **`VT_S3_*`**, OAuth-секреты.
4. Миграции Alembic применены к целевой БД.
5. Запущены **worker** и **worker-final**; при необходимости — diarization и GPU-профили ([docker/README.md](../docker/README.md)).
6. Smoke: `GET /health` на API и Admin API; вход в Web UI и при использовании — Admin Web UI.
7. (Рекомендуется) SBOM/скан образов перед приёмкой в prod.

---

## 7. Уточняющие вопросы к владельцу площадки (Compose / ВМ)

1. **Container registry** и политика тегов (один образ API на все роли или отдельные репозитории).
2. **TLS и публичные URL** для API, Web UI и Admin Web UI (для прошивки в `VITE_*` и OAuth).
3. Для внешней БД: **резервное копирование**, версия PostgreSQL, требования **SSL** к соединению из контейнеров.
4. Для внешнего S3: политика **IAM** (минимальные права на bucket), нужен ли **отдельный prefix** внутри bucket (если потребуется доработка приложения — зафиксировать в backlog).

---

## 8. Принятые направления улучшения (что уже есть и что в backlog)

| Направление | Статус |
|-------------|--------|
| Единые команды сборки без копипаста | **[Makefile](../Makefile)** в корне: `docker-build`, `release-cli`, `release-extension`, `release-artifacts` |
| CI: артефакты CLI и расширения | [.github/workflows/release-artifacts.yml](../.github/workflows/release-artifacts.yml) (ручной запуск и теги `v*`) |
| SBOM / скан уязвимостей образов | В документе (раздел 3.2); целевой процесс — перед prod на все публикуемые образы |
| Версионирование API и changelog для CLI/расширения | Backlog: привязать к релизам и ломающим изменениям в [openapi.yaml](../openapi.yaml) |
| Пример compose «только приложение» без встроенных Postgres/MinIO | Backlog площадки или репозитория: сайт-специфичный файл, чтобы не поднимать неиспользуемые сервисы при внешней БД/S3 |

При необходимости следующий шаг — внутренний лист «наш стенд»: таблица публичных URL и финальный `.env` без секретов в git.
