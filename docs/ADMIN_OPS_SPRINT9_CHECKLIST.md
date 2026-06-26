# Ops-консоль: спринт 9 — диагностика пайплайна (без управления Docker)

**Связь:** [ADMIN_OPS_CONSOLE.md](./ADMIN_OPS_CONSOLE.md) (§1, §3, §4.1–§4.2, §5.1, §9), [ADMIN_OPS_ROADMAP.md](./ADMIN_OPS_ROADMAP.md).  
**База:** спринт 8+ (`pipeline_events`, прогресс ASR, `GET /infrastructure` с очередями Celery).  
**Мотивация:** инциденты первого prod-деплоя (OOM/CUDA, очередь `diarization` без consumer, зависшие `pending`/`running`, рассинхрон UI и БД) выявлялись через `docker logs`, `psql` и `curl`, хотя сигналы уже частично есть в Admin API.

**Вне области спринта 9 (как и в baseline §2):** перезапуск контейнеров, правка `voice-transcriber.env`, сборка образов — по-прежнему на хосте/CLI. В UI допускаются только **read-only runbook-подсказки** (текст «на хосте выполните …»), без вызова Docker API.

---

## Порядок PR (рекомендуемый)

1. **PR-1** — Epic A (инфраструктура + S3 + алерты очередей) + unit-тесты Admin API.
2. **PR-2** — Epic B (`/diagnostics/summary`, фильтры «требует внимания») + UI вкладки «Инфра» / виджет сводки.
3. **PR-3** — Epic C (коды ошибок в `pipeline_events` из воркеров) — можно начать параллельно PR-1, если контракт `reason_code` зафиксирован заранее.
4. **PR-4** — Epic D (карточка разговора: таймлайн, диагноз, события inline).
5. **PR-5** — Epic E (`reset-stuck-transcript`, OpenAPI, аудит) + Epic F (топология Celery workers) — по готовности inspect.
6. **PR-6** (опционально) — Epic G (продуктовый Web UI: `failed` на tier final) — отдельный PR в `webui`, не блокирует админку.

---

## Уточнить при старте спринта

| Вопрос | Варианты / решение по умолчанию |
|--------|----------------------------------|
| Порог «зависшей» ревизии (`stale`) | **30 мин** для `pending`/`running` без новых `pipeline_events` |
| S3 в инфраструктуре | `head_bucket` + опционально `list_objects_v2` с `MaxKeys=1` по префиксу smoke; без чтения пользовательских объектов |
| Коды `reason_code` в событиях | Whitelist: `cuda_oom`, `cuda_unavailable`, `s3_error`, `ffmpeg_error`, `timeout`, `admin_reset`, `exception` (legacy) |
| Runbook-тексты | Статические строки в admin-webui или i18n-файл; не подтягивать compose-профили с хоста |
| GPU / nvidia-smi | **Не в v1** спринта 9 (backlog Epic H); только текстовая подсказка при `cuda_*` |

---

## Epic A: инфраструктура и алерты очередей

**Цель:** вкладка «Инфраструктура» отвечает на вопрос «что сломано» без разбора JSON.

- [ ] **A1** Расширить `GET /admin/api/v1/infrastructure`: блок **`s3`** (`ok`, `detail`) — `head_bucket` с `app_config.s3.*`; таймаут ≤ 3 с.
- [ ] **A2** Для каждой строки `celery_queues` добавить поля **`severity`** (`ok` | `warning` | `critical`) и **`hint`** (короткий текст на русском, без секретов).
- [ ] **A3** Правила severity (минимум):
  - `queue_depth > 0` и `consumer_responding == false` → **critical**;
  - `queue_depth > 10` и consumer есть → **warning**;
  - `consumer_responding == false` и depth == 0 → **warning** (воркер не поднят, очередь пока пуста).
- [ ] **A4** Статический маппинг `queue` → **ожидаемый compose-сервис** (поле `expected_service`, напр. `diarization` → `diarization-worker-gpu` / `diarization-worker`) — только подсказка, не проверка Docker.
- [ ] **A5** admin-webui: вкладка «Инфраструктура» — таблица/карточки вместо голого JSON; сворачиваемый блок «Сырой JSON».
- [ ] **A6** Unit-тесты: мок S3/Celery inspect; сценарий «diarization depth=4, consumer=false» → critical.

---

## Epic B: сводка «Требует внимания» и фильтры списка

**Цель:** один экран для оператора: что чинить в первую очередь.

- [ ] **B1** `GET /admin/api/v1/diagnostics/summary` (или расширение `/infrastructure` полем `attention`):
  - счётчики: ASR `failed` за 24 ч; зависшие ASR/diarization (по порогу stale);
  - список очередей critical из Epic A;
  - последние N событий `asr_failed` / `diarization_failed` (id разговора, `reason_code`, время) — без §9.
- [ ] **B2** Запросы с лимитами и индексами (`pipeline_events`, `transcripts`); без full table scan.
- [ ] **B3** `GET /admin/api/v1/conversations`: пресеты query (согласовать имена):
  - `attention=1` — объединение «failed или stale»;
  - или отдельно `stale_minutes`, `include_diarization_pending`.
- [ ] **B4** admin-webui: блок «Требует внимания» на вкладке списка; кнопки-фильтры («ASR failed», «Зависло», «Ждёт diarization»).
- [ ] **B5** Тесты §9 и 403 для новых маршрутов.

---

## Epic C: коды ошибок в пайплайне (воркеры + `pipeline_events`)

**Цель:** причина OOM/CUDA/S3 видна в админке без `docker logs`.

- [ ] **C1** Расширить whitelist `reason_code` в [pipeline_event_write.py](../server/app/services/pipeline_event_write.py) (и документировать в чеклисте).
- [ ] **C2** В [workers/tasks/asr.py](../server/workers/tasks/asr.py) при `asr_failed`: классификация исключения → `cuda_oom`, `cuda_unavailable`, `s3_error`, … (без текста пользователя в `detail`).
- [ ] **C3** Аналогично для diarization task при `diarization_failed`.
- [ ] **C4** (опционально) Короткий `error_hint` в `transcripts` при переходе в `failed` — только техническая строка ≤ 200 символов, без transcript text.
- [ ] **C5** Unit-тесты классификатора ошибок (табличные кейсы по сообщению исключения).

---

## Epic D: карточка разговора — таймлайн и диагноз

**Цель:** разбор одного `conversation_id` без SQL.

- [ ] **D1** API: в `GET /admin/api/v1/conversations/{id}` (или подресурс `/timeline`) — упорядоченные **шаги**: ревизии transcripts + `pipeline_events` + статус `recording_session_summary` (без текста расшифровки).
- [ ] **D2** Поле **`diagnosis`** (read-only string): правила на сервере (примеры):
  - ASR success + diarization pending + очередь diarization без consumer → текст про воркер;
  - последнее `asr_failed` + `reason_code=cuda_oom` → текст про VRAM;
  - revision `running` stale → «зависшая задача».
- [ ] **D3** Для tier-подобной логики: явно отдавать **последнюю ASR-ревизию любого статуса** (аналог fix продукта: final view при `failed`).
- [ ] **D4** admin-webui: карточка — таймлайн + диагноз + кнопки действий; JSON — в «Подробности».
- [ ] **D5** Встроить последние 20 `pipeline_events` по разговору в карточку (не только глобальная вкладка).
- [ ] **D6** Тесты: сценарий «failed ASR + пустой success final» → diagnosis не «в обработке».

---

## Epic E: мутация «сброс зависшей ревизии»

**Цель:** заменить ручной `UPDATE transcripts SET status='failed'`.

- [ ] **E1** `POST /admin/api/v1/conversations/{id}/actions/reset-stuck-transcript` → 202 или 200:
  - body: `kind` (`asr` | `asr_diarized`), опционально `force`, `stale_minutes`;
  - условие: `pending`/`running` и (stale **или** force с подтверждением в UI).
- [ ] **E2** Побочные эффекты: `status → failed`, `pipeline_events` с `reason_code=admin_reset`, запись в `admin_audit_events`.
- [ ] **E3** 409 если идёт «живая» задача (моложе порога и не force).
- [ ] **E4** admin-webui: кнопка в карточке при diagnosis «зависло»; confirm dialog.
- [ ] **E5** OpenAPI + unit-тесты (401/403/409/успех).

---

## Epic F: топология Celery-воркеров

**Цель:** видеть, кто слушает `asr_fast` / `diarization`, без чтения env на сервере.

- [ ] **F1** `GET /admin/api/v1/celery-workers`: из `inspect.active_queues` — hostname, список очередей, concurrency (если доступно).
- [ ] **F2** Предупреждения в ответе (`warnings[]`):
  - два разных worker на одной «критичной» очереди при gpu-деплое (эвристика);
  - `asr_final` без consumer;
  - `asr_fast` только на CPU-worker при ожидании GPU final (эвристика по имени очереди).
- [ ] **F3** Кэш 10–15 с (как `celery_monitor`); не блокировать request надолго.
- [ ] **F4** admin-webui: секция на вкладке «Инфра» или «Пайплайн».
- [ ] **F5** Расширить `GET /pipeline-settings` non-secret полями из env воркера/api: `VT_ASR_DEVICE`, `VT_ASR_MODEL`, `VT_MAIN_WORKER_QUEUES` (если заданы) — для сверки с фактическими очередями inspect.

---

## Epic G: продуктовый Web UI (связанный, не admin-api)

**Цель:** пользователь не видит «в обработке» при `failed` на вкладке «Финальный».

- [ ] **G1** API продуктового `GET /conversations/{id}`: для `tier=final` отдавать последнюю ASR-ревизию при отсутствии success (уже в работе в репозитории — зафиксировать в DoD).
- [ ] **G2** Web UI: `isTranscriptProcessing` учитывает `transcriptStatus === 'failed'`; tooltip кнопки «Распознать снова» различает busy vs failed.
- [ ] **G3** Приёмка: сценарий из prod (upload → failed → кнопка активна).

---

## Epic H: backlog (после спринта 9)

- [ ] **H1** SSE/WebSocket для алертов и ленты (перенос C1 спринта 8).
- [ ] **H2** Ретенция и cleanup `pipeline_events`.
- [ ] **H3** Опциональный snapshot GPU (nvidia-smi) с хоста admin-api — только если безопасно на площадке.
- [ ] **H4** Проверка доступности **внешнего** LLM (vLLM URL из config) в infrastructure — HTTP ping без промптов.
- [ ] **H5** Фильтр списка «рассинхрон с продуктом» (эвристика: latest asr failed, UI polling refetch).

---

## Финальная приёмка (Definition of Done)

- [ ] Оператор без shell воспроизводит сценарии приёмки:
  1. Остановлен `diarization-worker-gpu`, в очереди есть задачи → **critical** на вкладке Инфра + diagnosis в карточке.
  2. ASR failed с `cuda_oom` → виден `reason_code` в событиях/карточке.
  3. Зависший `running` → diagnosis + reset-stuck → retranscribe из продукта или admin action без 409.
- [ ] §9: ни в одном новом поле нет текста расшифровки и аудио.
- [ ] OpenAPI обновлён для новых маршрутов.
- [ ] Unit-тесты Admin API зелёные (`docker compose run --rm tests` — релевантный поднабор).

---

## Сценарии приёмки (чеклист ручной)

| # | Действие | Ожидание в админке |
|---|----------|-------------------|
| 1 | `stop diarization-worker-gpu`, в Redis depth>0 | Critical на `diarization`, hint с именем сервиса |
| 2 | Retranscribe при stale `running` без воркера | Диагноз «зависло»; reset-stuck → retranscribe OK |
| 3 | ASR OOM (или тестовый `asr_failed` с `cuda_oom`) | Событие и diagnosis упоминают VRAM |
| 4 | S3 недоступен | `s3.ok=false` в infrastructure |
| 5 | Список «ASR failed» | Только разговоры с failed active/latest ASR |

---

## История документа

| Дата | Изменение |
|------|-----------|
| 2026-06-23 | Первая версия: спринт 9 — диагностика пайплайна по итогам prod-деплоя. |
