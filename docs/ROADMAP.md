# Дорожная карта реализации Voice Transcriber

**Канон постановки:** [TECHNICAL_SPECIFICATION.md](./TECHNICAL_SPECIFICATION.md)  
**Правило:** новые HTTP-эндпоинты сначала в `openapi.yaml` (когда появится), затем backend и клиенты.

Ниже чекбоксы для отметки выполнения (`[x]` / `[ ]`). Пометки по ходу — в конце файла или под соответствующим этапом.

---

## Этап 0 — Фундамент

- [x] **0.1** Добавить `openapi.yaml` (OpenAPI 3) с путями из ТЗ §3.3
- [x] **0.2** Договориться о публикации `/docs` (импорт YAML / CI-проверка схемы) — см. [OPENAPI.md](./OPENAPI.md)
- [x] **0.3** Миграция БД: `recording_session_id`, `previous_conversation_id` на `conversations` (ТЗ §7)
- [x] **0.4** Конфиг + ответ `GET /api/settings/limits`: `autoprolong_tail_*`, при необходимости флаги autoprolong
- [x] **0.5** ADR или краткий раздел в ТЗ: единый механизм ASR (`registry` / `factory`)

---

## Phase A — Базовый продукт

**Приёмка (ТЗ §8):** логин → создать разговор → upload → список/просмотр → export → limits из API → поиск GET; допускается stub ASR.

### Backend

- [x] **A1.1** `GET/PATCH /api/settings/user` (`GET /api/settings/limits` — Этап 0 ✓)
- [x] **A1.2** `GET /api/conversations/{id}/export?format=md|json`
- [x] **A1.3** `GET /api/search` согласован с OpenAPI и fulltext (semantic — по готовности)
- [x] **A1.4** `POST /api/conversations` с валидацией от limits (realtime/chunk/TTL)
- [x] **A1.5** `POST /api/upload` + Celery; stub ASR → валидный `transcript.json` в S3
- [x] **A1.6** Единый секрет JWT: переменная **`VT_JWT_SECRET`** (API/воркер/CLI); иначе fallback на `client_secret` Google из `configs/server.yaml` — см. `server/core/security.py`, [docker/README.md](../docker/README.md)

### Web UI

- [x] **A2.1** Поиск: переход на `GET` + query-параметры
- [x] **A2.2** Подключение limits и user settings; кламп полей по серверу
- [x] **A2.3** Скачивание через `export` (md/json)
- [x] **A2.3b** Пакетная загрузка аудио со страницы списка разговоров: **`POST /api/upload`** (тот же контракт, что у CLI `upload` / `scripts/phase_a_upload_smoke.py`)
- [x] **A2.4** Чеклист приёмки Phase A: [PHASE_A_ACCEPTANCE.md](./PHASE_A_ACCEPTANCE.md) (ручное прохождение; при смене UI обновлять пункты)
- [x] **A2.5** Запись с **микрофона** на странице списка разговоров: MediaRecorder → файл → тот же **`POST /api/upload`** после «Stop & upload» (без realtime WebSocket)

### CLI

- [x] **A4.1** Устанавливаемый пакет `cli/`, команда **`transcriber`**: `upload`, `conversations list|show`, `export`, `audio`, `delete`, `me`; контракт с Web UI (`POST /api/upload` и др.)

### Инфраструктура и тесты

- [x] **A3.1** Docker Compose (`docker/docker-compose.yml`): сервисы Phase A, проброс портов, migrate → api (healthcheck) → webui; документация [docker/README.md](../docker/README.md); JWT см. `VT_JWT_SECRET`
- [x] **A3.2** Интеграционный e2e: `server/tests/integration/test_phase_a_upload_export_e2e.py` (env `VT_E2E_BASE_URL`, `VT_E2E_TOKEN`); см. [TESTING.md](./TESTING.md)

**Phase A закрыта:** [x] да (чеклист + compose + A3.2) **Дата:** 2026-04-18

---

## Phase B — Realtime и расширение

**Приёмка:** create conversation → WS audio → partial transcript; лимиты; v1 один источник (мик **или** вкладка). Дополнительно по ASR — см. **B3.4** (реальный inference для всех заявленных вариантов).

### Backend WebSocket

- [x] **B1.1** URL в OpenAPI + [WEBSOCKET.md](./WEBSOCKET.md); префикс **`/ws`** (не `/api`)
- [x] **B1.2** `/ws/audio`: буфер chunk/windowed (`ws_realtime_buffer.py`), кламп по limits + полям разговора, `core.asr_chunk.transcribe_audio_chunk_bytes`
- [x] **B1.3** `/ws/transcript`: `TranscriptHub` — memory или Redis (`VT_TRANSCRIPT_REDIS`, `ws_hub_redis.py`)
- [x] **B1.4** MVP: JWT через `access_token` или `bearer.<JWT>` в subprotocol; проверка владельца разговора; prod short-lived — Phase C
- [x] **B1.5** Единый registry + `build_asr_provider` (`app/asr/factory.py`), `recognition_model` в `configs/asr.yaml` / `VT_ASR_MODEL`; wired placeholder в `app/asr/*` до реального inference; batch + chunk. Детали: [ASR_PROVIDER_IMPLEMENTATION.md](./ASR_PROVIDER_IMPLEMENTATION.md)

### Расширение браузера

- **Канон UX:** [BROWSER_EXTENSION_UI.md](./BROWSER_EXTENSION_UI.md). **Канон аутентификации и сессии:** [AUTH_AND_IDENTITY.md](./AUTH_AND_IDENTITY.md).
- Существенная переработка интерфейса и поведения (Side Panel вместо «всё в popup», контекстное меню, модель persist, жизненный цикл записи) вынесена в отдельные пункты **B2.6–B2.8**; пункты **B2.0–B2.5** — техническая доводка API/OAuth/WS/manifest/upload под тот же канон.
- [x] **B2.0** OAuth в расширении: **гибридный** вход — сначала `launchWebAuthFlow` с `interactive: false` + `prompt=none` (Google) / эквивалент Яндекс; при отсутствии `code` — вторая попытка `interactive: true`; без «ложных» ошибок в UI при ожидаемом провале silent-шага. **C7.1** (обмен `code` на сервере без mock) — Phase C; клиентский поток Phase B выполнен.
- [x] **B2.1** `POST /api/conversations` перед записью, сохранение `conversation_id`
- [x] **B2.2** Подключение `TranscriptWebSocketClient` к UI; reconnect при необходимости для audio
- [x] **B2.3** Manifest: `tabCapture`, host permissions
- [x] **B2.4** Кнопка загрузки файла → `POST /api/upload`
- [x] **B2.5** При необходимости MV3: offscreen / перенос записи из service worker
- [x] **B2.6** **Целевая рабочая поверхность — Chrome Side Panel:** запись и WebSocket (`/ws/audio`, `/ws/transcript`) в контексте панели (не в service worker), индикаторы соединения/ASR, **Reconnect**, выгрузки через те же канонические HTTP, что Web UI (`GET …/export` и последующие эндпоинты по `openapi.yaml`). Ориентир по UX и ограничениям платформы — [BROWSER_EXTENSION_UI.md](./BROWSER_EXTENSION_UI.md) §2.1, §5.1.
- [x] **B2.7** **Popup — только «лёгкий вход»:** авторизация (в т. ч. целевой поток **B2.0**), настройки, открытие/фокус Side Panel; **`chrome.contextMenus`** на иконке (Start/Stop, upload файла, настройки и т. п. по документу); **persist** сессий в `chrome.storage` по **`windowId`** и вкладкам контекста; service worker — OAuth-редиректы, маршрутизация, меню, обработчики закрытия вкладок/окон **без** записи и без тяжёлого UI в SW — [BROWSER_EXTENSION_UI.md](./BROWSER_EXTENSION_UI.md) §2.2–§3. *Часть §3 (несколько вкладок-«чипов», кап превью на вкладку) отложена — [PHASE_B_ACCEPTANCE.md](./PHASE_B_ACCEPTANCE.md).*
- [x] **B2.8** **Жизненный цикл записи:** закрытие Side Panel **не** останавливает запись; закрытие **вкладки** или **окна**, к которым привязана активная сессия, — безопасный Stop и закрытие WS; на сервере при разрыве audio-WS — **flush в `finally`** до JSON **`finalize`** / ТЗ §17 — [BROWSER_EXTENSION_UI.md](./BROWSER_EXTENSION_UI.md) §2.4, [WEBSOCKET.md](./WEBSOCKET.md).

### ASR (минимум для realtime)

- [x] **B3.1** Декод WebM/Opus → PCM (`core/webm_pcm.py`, ffmpeg в `Dockerfile.api`; one-shot для тестов)
- [x] **B3.2** Режим chunk end-to-end (PCM + `RealtimeAudioBuffer`)
- [x] **B3.3** Режим windowed (тот же буфер; legacy без ffmpeg — по байтам)
- [x] **B3.4** **Реальный inference** для заявленных вариантов (`configs/asr.yaml`): **whisper** и **faster_whisper** — faster-whisper/CTranslate2 в `app/asr/`; **vosk** — при заданном `VOSK_MODEL_PATH` или `model_path`. **Автотесты:** маркер `asr_inference`, эталон [`server/tests/sample-1.webm`](../server/tests/sample-1.webm), см. [TESTING.md](./TESTING.md); пропуск: `VT_SKIP_ASR_INFERENCE=1`. **Ручная приёмка:** Web UI / `POST /api/upload` с выбранными тестирующим файлами для каждого движка (переключение `default_provider`).

**Phase B закрыта:** [x] да **Дата:** 2026-04-26 **Чеклист приёмки:** [PHASE_B_ACCEPTANCE.md](./PHASE_B_ACCEPTANCE.md)

---

## Phase C — Расширенные возможности

- [x] **C1** Post-hoc diarization + **серверная** настройка автозапуска в pipeline (`configs/diarization.yaml` и деплой; **не** переключатель в Web UI) (канон: [DIARIZATION_ALIGNMENT_VERSIONING.md](./DIARIZATION_ALIGNMENT_VERSIONING.md)) — ручная приёмка: [PHASE_C_ACCEPTANCE.md](./PHASE_C_ACCEPTANCE.md)
  - [x] **C1.1** Транскрипты: версионирование + `active_transcript_id` (Scheme 2) — хранить историю, отдавать только активную
  - [x] **C1.2** Rerun diarization: endpoint + UI confirm (перезапись = новая версия, promote только на success)
  - [x] **C1.3** Провайдер `pyannote` + отдельный образ воркера: в compose **два** сервиса — `diarization-worker` (CPU wheels, build-arg `DIARIZATION_TORCH=cpu`) и `diarization-worker-gpu` (CUDA wheels, профиль `gpu`, `DIARIZATION_TORCH=cuda`); см. [docker/README.md](../docker/README.md#diarization-cpu-vs-cuda-images)
- [x] **C1.4** Идентификация и переименование спикеров (LLM + UI): [SPEAKER_IDENTIFICATION.md](./SPEAKER_IDENTIFICATION.md) — фазы **S1** (ручной rename) → **S2** (LLM suggest) → **S3** (summary/embeddings)
- [x] **C2** Semantic search (embeddings), если не сделано в A
- [x] **C3** Автопродление (ТЗ §7): триггеры, хвост в A, связи в БД
- [x] **C4** Dual capture (микрофон + вкладка) → микширование в один `audio.webm`
- [x] **C5** Метрики Prometheus (или эквивалент) по минимальному набору ТЗ §16
- [x] **C6** CLI: API key, цепочка разговоров, JSON + exit code + polling
- [x] **C7** Прод: CORS, секреты, OAuth, политика токенов в WS — канон требований: [AUTH_AND_IDENTITY.md](./AUTH_AND_IDENTITY.md); регрессия: [PHASE_C_ACCEPTANCE.md](./PHASE_C_ACCEPTANCE.md)
  - [x] **C7.1** Реальный обмен OAuth `code` на backend (Google, Yandex): token endpoint + userinfo / `id_token`, создание/поиск пользователя по **`(provider, sub)`**; убрать mock в `extension/finalize` и callback Web UI; **`refresh_token` провайдера не хранить** для текущих сценариев
  - [x] **C7.2** Долгая сессия **сервиса**: refresh-токен (или эквивалент) + **`POST /api/auth/refresh`** (имя согласовать в `openapi.yaml`), ротация/отзыв; короткий access JWT для REST/WS
  - [x] **C7.3** Защита публичного клиента расширения: **PKCE** + **state** (или эквивалент) на цепочке authorize → finalize; не дублировать построение authorize URL — опираться на **`GET /api/auth/{provider}/extension/start`**
  - [x] **C7.4** **Web UI:** слияние аккаунтов — таблица связей пользователь↔провайдерский субъект, UI-поток подтверждения; после слияния любой привязанный провайдер ведёт к одному `user_id` при корректном поиске в C7.1
  - [x] **C7.5** Политика токенов в **WebSocket** prod: только subprotocol `bearer.<JWT>`; query отключён при `VT_ENVIRONMENT=production` (override: `VT_WS_ALLOW_QUERY_TOKEN`, `VT_WS_REQUIRE_SUBPROTOCOL`) — `WEBSOCKET.md`, `ws_auth.py`

**Phase C закрыта:** [ ] да / [ ] нет **Дата:** ___________

---

## ТЗ §17 — сегментация, fast/final, `finalize`, чанки upload

**Постановка зафиксирована:** [TECHNICAL_SPECIFICATION.md §17](./TECHNICAL_SPECIFICATION.md). Чеклист готовности **§17.11** там же должен совпадать по смыслу с отметками в этой секции дорожной карты.

- [x] **`visibility_timeout` Celery:** переменная **`VT_CELERY_VISIBILITY_TIMEOUT`** (секунды), в compose по умолчанию **14400**; см. `workers/celery_app.py`, [docker/README.md](../docker/README.md)
- [x] **WS `finalize` / `finalize_id`:** канал `/ws/audio` принимает JSON `finalize`, ответ `finalize_ack` / `duplicate`, Redis SET NX при **`VT_REDIS_URL`**; см. [WEBSOCKET.md](./WEBSOCKET.md), `app/api/ws_finalize_store.py`
- [x] **`processing_tier: fast`** в событиях **`transcript_partial`** (hub)
- [x] **`finalize` → S3 + fast transcript + Celery `transcribe_file` с `transcript_meta_extra`** (`realtime_finalize.py`, `websocket.py`)
- [x] **REST/export:** query **`tier=auto|fast|final`** (`conversations.py`, `openapi.yaml`)
- [ ] OpenAPI codegen только для WS (WS полностью не в OAS) — по необходимости
- [x] **Очереди `asr_fast` / отдельно от `asr_final`:** `transcribe_slice` → **`asr_fast`**, `transcribe_file` и **`finalize_parallel_transcript`** → **`asr_final`**; compose **`worker`:** `--queues=asr_fast,asr,llm,cleanup`; **`worker-final`:** `asr_final` — см. `workers/celery_app.py`, `docker-compose.yml`
- [x] **Нарезка/merge длинного upload + final pipeline:** последовательный chunking и параллельный chord + merge в **`workers/tasks/asr.py`** (`VT_ASR_CHUNK_SECONDS`, **`VT_ASR_PARALLEL_CHUNKS`**)
- [x] **Web UI / расширение (§17.8–§17.9):** Web UI — переключатель Fast/Final и метаданные стадии на **`ConversationViewerPage`**; расширение — канонический **`GET /export`** с **`tier=final`**, кнопки final до **`transcript_status=success`** неактивны; локально «Save live text» для live/fast

### Realtime v2 (расширение + persist fast) — [REALTIME_FAST_FINAL_V2.md](./REALTIME_FAST_FINAL_V2.md)

- [ ] **R1:** дефолт `windowed`; **`finalize`** в расширении; без дублирующего upload после finalize
- [ ] **R2:** периодический persist **fast** в БД (`fast_persist_interval_s`); Web UI poll черновика во время записи
- [ ] **R3:** разделение `media_chunk_ms` / `asr_step_ms` в API и расширении
- [ ] **R4:** overlap окон ASR + merge по таймкодам
- [ ] **R5:** образ/compose API для CUDA realtime (`nvidia-*`, GPU passthrough)
- [ ] **R6 (опц.):** fast через Celery `asr_fast` при перегрузке API

---

## Параллельно (не блокируют A)

- [x] LLM summary + решение по цепочке автопродления (ТЗ §7.6) — rolling summary на `recording_session_id`, см. `TECHNICAL_SPECIFICATION.md` §7.6
- [x] Ссылка из `docs/README.md` на ТЗ и дорожную карту
- [ ] Пометка в устаревших `main_*` / «канон — TECHNICAL_SPECIFICATION»
- [x] Нагрузка Celery: отдельные очереди/масштабирование воркеров по мере роста — очереди уже разведены (`asr_fast`, `asr_final`, `asr`, `llm`, `diarization`, `cleanup`); compose: **`VT_MAIN_WORKER_QUEUES`**, профиль **`scale_llm`** + сервис **`worker-llm`**, см. [docker/README.md](../docker/README.md)

---

## Рекомендуемые первые спринты (ориентир)

| Спринт | Фокус |
|--------|--------|
| **1** | 0.1–0.2, A1.1–A1.2, A2.1–A2.3 (контракт + UI под limits/export/search) |
| **2** | 0.3–0.5, A1.4–A1.5, A2.4, A3 (миграции, stub ASR, приёмка Phase A) |
| **3** | Phase B: B1.5 провайдеры ASR → B2 расширение; параллельно WS + B3 (уже по чеклисту) |
| **4+** | Подэпики Phase C по приоритету продукта; **C7.x** (OAuth/сессия/слияние) — [AUTH_AND_IDENTITY.md](./AUTH_AND_IDENTITY.md) |

---

## Пометки по мере реализации

*(Добавляйте дату и краткий текст: что сделано, что отложено, ссылки на PR/issue.)*

| Дата | Этап / пункт | Пометка |
|------|----------------|---------|
| 2026-04-18 | Этап 0 | `openapi.yaml`, `docs/OPENAPI.md`, расширение `limits.yaml` + `LimitsConfig`, `GET /api/settings/limits`, поля `Conversation` + Alembic `stage0_001`, ADR 0001, правки ТЗ v1.1 |
| 2026-04-18 | Phase A (часть) | Миграция `phase_a_002` (user.preferences, client realtime), settings/user, export, детальный GET conversation, stub ASR + Transcript в БД, поиск `cast` String, Web UI: GET search, limits snake_case, export md |
| 2026-04-18 | Phase A закрытие | A3.1 compose+healthcheck+доки; A1.6 `VT_JWT_SECRET`; A2.4 [PHASE_A_ACCEPTANCE.md](./PHASE_A_ACCEPTANCE.md) |
| 2026-04-18 | Phase B (старт) | [WEBSOCKET.md](./WEBSOCKET.md), `openapi.yaml` `/ws/*`, FastAPI `/ws/audio|transcript`, B1.1/B1.4 |
| 2026-04-18 | Phase B (план) | B1.5: единый registry + реализации ASR до B2 — [ASR_PROVIDER_IMPLEMENTATION.md](./ASR_PROVIDER_IMPLEMENTATION.md) |
| 2026-04-18 | Phase B (B1.5) | `recognition_model` в `configs/asr.yaml`, `build_asr_provider`, wired placeholder до ML inference |
| 2026-04-18 | Phase B (требование) | B3.4: реальный inference по всем заявленным провайдерам; ручные файлы тестера + автотест `server/tests/sample-1.webm` |
| 2026-04-19 | Phase B (B3.4) | faster-whisper + Vosk, pytest `asr_inference`, [TESTING.md](./TESTING.md) |
| 2026-04-20 | Phase C (C1.1–C1.3) | Версии транскриптов + `active_transcript_id`; rerun diarization (`POST /api/conversations/{id}/diarize`) + UI confirm + 409 guard; pyannote + `diarization-worker` / `diarization-worker-gpu` (build-arg `DIARIZATION_TORCH`, см. docker/README); автозапуск diarization — только серверный конфиг, не UI-тумблер для пользователя |
| 2026-04-23 | Auth / roadmap | [AUTH_AND_IDENTITY.md](./AUTH_AND_IDENTITY.md) — канон требований; ТЗ §3.4; **B2.0**, детализация **C7.1–C7.5** |
| 2026-04-23 | Phase B закрытие | Расширение: shell popup + side panel, context menus (Start / Stop / Upload / Settings / Open panel), offscreen mic, persist `RecordingSessionV1`, export/refresh GET, Vitest в `browser-extension/`; приёмка — [PHASE_B_ACCEPTANCE.md](./PHASE_B_ACCEPTANCE.md) |
| 2026-04-30 | Phase C (C7.1, C7.3) | Реальный OAuth (Google/Yandex): httpx token + userinfo; таблица `user_oauth_identities`; Web UI `state` JWT; расширение PKCE + подписанный `state`, authorize только через `extension/start`; compose **`VT_PUBLIC_API_URL`** для redirect_uri с Docker |
| 2026-04-30 | Phase C (C7.2) | Таблица `auth_refresh_sessions` (хранится SHA-256 refresh); выдача при OAuth Web/extension; **`POST /api/auth/refresh`** с ротацией; Web UI: fragment `refresh_token` + axios interceptor; расширение: `refreshToken` в storage + `verifyOrRefreshSession`; **`VT_REFRESH_TOKEN_TTL_DAYS`** |
| 2026-04-30 | Phase C (C7.4) | Привязка провайдеров в Web UI: JWT state `vt_oauth_web_link`; **`GET /api/auth/{provider}/link/start|callback`**; **`GET /api/settings/oauth-identities`**; страница Settings — список + Link Google/Yandex; конфликты → redirect `?oauth_link=error&reason=` |
| 2026-04-30 | Phase C (C7 + C1) | Родительские пункты **C7**, **C1** отмечены выполненными по коду и конфигам; чеклист ручной приёмки и порядок проверки — [PHASE_C_ACCEPTANCE.md](./PHASE_C_ACCEPTANCE.md); обновлён статус в [DIARIZATION_ALIGNMENT_VERSIONING.md](./DIARIZATION_ALIGNMENT_VERSIONING.md) |
| 2026-05-01 | ТЗ §17 + документация | Закрыты очереди **`asr_fast`/`asr_final`**, chunking/merge, UX §17.8–§17.9; согласованы **§17.11** ТЗ и [PHASE_B_ACCEPTANCE.md](./PHASE_B_ACCEPTANCE.md) (**finalize**, export **`tier=final`**); backlog — codegen WS, OpenAPI-детализация полного JSON разговора |
| 2026-06-23 | Зависимости сервера | [DEPENDENCIES_MIGRATION.md](./DEPENDENCIES_MIGRATION.md): **Python 3.12**, pyannote 4 + torch 2.10 + hf_hub 1.x; фазы **4, 5a** (GigaAM в lock, `install-torch.sh`) |
| 2026-06-24 | Зависимости / деплой | **Unified GPU worker** (`worker-gpu-unified`, profile `gpu-unified`); фазы 0–7 и 5b закрыты |
| 2026-06-25 | C1.4 / спикеры | План [SPEAKER_IDENTIFICATION.md](./SPEAKER_IDENTIFICATION.md): LLM identify + rename, фазы S1–S3 |

---

## История дорожной карты

| Версия | Дата | Изменение |
|--------|------|------------|
| 1.1 | 2026-04-18 | Этап 0 отмечен выполненным |
| 1.0 | 2026-04-18 | Первоначальная дорожная карта по ТЗ v1.0 |
| 1.2 | 2026-04-18 | Phase B: пункт B1.5 (реализации ASR до B2), [ASR_PROVIDER_IMPLEMENTATION.md](./ASR_PROVIDER_IMPLEMENTATION.md) |
| 1.3 | 2026-04-18 | B1.5 выполнен: registry↔factory, `recognition_model`, wired `[ASR wired]` |
| 1.4 | 2026-04-18 | Phase B: B3.4 — реальный ASR inference для всех заявленных провайдеров; приёмка + `server/tests/sample-1.webm` для автотестов |
| 1.5 | 2026-04-19 | B3.4 реализован: faster-whisper, vosk, тесты `-m asr_inference` |
| 1.6 | 2026-04-20 | C1: уточнение формулировки — автозапуск diarization только серверный конфиг, не UI-переключатель для пользователя |
| 1.7 | 2026-04-20 | C1.3 + журнал: явно два compose-сервиса diarization и build-arg `DIARIZATION_TORCH` (как в docker/README) |
| 1.8 | 2026-04-23 | B2.0 (гибрид OAuth расширения); C7 разбит на C7.1–C7.5 + ссылка на AUTH_AND_IDENTITY.md |
| 1.9 | 2026-04-23 | Phase B: явные пункты **B2.6–B2.8** — крупная доработка UI/UX расширения (Side Panel, popup, context menus, persist, жизненный цикл) по [BROWSER_EXTENSION_UI.md](./BROWSER_EXTENSION_UI.md) |
| 1.10 | 2026-04-23 | Phase B закрыта: B2.0–B2.8 отмечены выполненными; [PHASE_B_ACCEPTANCE.md](./PHASE_B_ACCEPTANCE.md); Vitest в `browser-extension/`; [TESTING.md](./TESTING.md) — раздел Phase B |
| 1.11 | 2026-04-30 | Phase C: родительские **C7**, **C1** закрыты по реализации; [PHASE_C_ACCEPTANCE.md](./PHASE_C_ACCEPTANCE.md) для ручной приёмки |
| 1.12 | 2026-05-01 | ТЗ §17: отмечены очереди **`asr_fast`/`asr_final`**, chunking/merge, Web UI + расширение (§17.8–§17.9); синхронизированы **§17.11** ТЗ и [PHASE_B_ACCEPTANCE.md](./PHASE_B_ACCEPTANCE.md); codegen WS — по необходимости |
