# ТЗ: доработка realtime, fast/final и расширения браузера (v2)

**Статус:** реализовано (релиз **v0.3.2**, 2026-06-30); дополняет [TECHNICAL_SPECIFICATION.md](./TECHNICAL_SPECIFICATION.md) §17, [WEBSOCKET.md](./WEBSOCKET.md), [BROWSER_EXTENSION_UI.md](./BROWSER_EXTENSION_UI.md).

**Версия:** 1.0  
**Дата:** 2026-06-30  
**Контекст:** эксплуатация gpu-unified (GigaAM final), live ASR на API (faster-whisper), расширение Chromium.

---

## 1. Проблема (as-is)

### 1.1. Качество live-расшифровки

- Режим **`chunk`** с шагом 0,5–2 с режет речь по таймеру → обрезание слов, неточный текст.
- Расширение **дописывает** каждый `transcript_partial` отдельной строкой; при плохих границах чанков UX усиливает ощущение «рваного» текста.
- Режим **`windowed`** и VAD есть на сервере, но **дефолт** в `configs/limits.yaml` и расширении — **`chunk`**.

### 1.2. Fast/final не дают продуктовой ценности

| Ожидание (§17) | Факт |
|----------------|------|
| **Fast** — сохранённый черновик на сервере, доступен в Web UI | Fast в БД создаётся только при WS **`finalize`**; расширение **`finalize` не шлёт** |
| **Live** в расширении | Partials только в памяти клиента (WebSocket) |
| **Stop** → fast + очередь final | Stop → **`POST /api/upload`** → только **final** (GigaAM) |
| Web UI «Быстрый» | Пусто: нет строки `transcripts` с `meta.processing_tier=fast` |

Upload (Web UI, CLI, расширение после Stop) **никогда** не создаёт fast — это корректно для пакетного файла, но **не** для realtime-сессии.

### 1.3. Инфраструктура realtime на GPU (справочно)

- Live ASR выполняется в контейнере **`api`** (`VT_ASR_REALTIME_*`), final — в **`worker-gpu-unified`**.
- Для CUDA на API нужны pip `nvidia-*`, `LD_LIBRARY_PATH` и проброс GPU в compose (см. §10).

---

## 2. Цели

1. **Качество черновика:** снизить обрезание слов за счёт **windowed**-окон, VAD и (фаза 2) overlap/merge по времени.
2. **Смысл fast:** во время и после realtime-сессии в БД есть ветка **fast**, просматриваемая в Web UI (`?tier=fast`) без открытого расширения.
3. **Смысл final:** без изменений — полный файл, GigaAM (или иной `final_provider`), диаризация по конфигу.
4. **Единый протокол Stop** для расширения: **`finalize`** на `/ws/audio` вместо дублирующего upload того же аудио.
5. **Настраиваемость:** гибрид «клиент на разговор + серверные границы + серверные интервалы снимков».

## 3. Не-цели (v1 данного ТЗ)

- Замена whisper realtime на GigaAM в live-потоке.
- Диаризация ветки **fast**.
- Полноценный «stable/unstable» UI как у коммерческих streaming API (допустим backlog).
- Realtime через Celery `asr_fast` вместо синхронного API (фаза 3, опционально).

---

## 4. Термины

| Термин | Значение |
|--------|----------|
| **Media chunk** | Порция WebM/Opus от `MediaRecorder` на клиенте (сеть). |
| **ASR step** | Порог PCM на сервере (`chunk_ms` в буфере) — как часто запускать whisper. |
| **ASR window** | Длина окна PCM в режиме `windowed` (`max_window_ms`). |
| **Partial** | Событие `transcript_partial` в WS / UI; не обязательно строка в БД. |
| **Fast snapshot** | Запись/обновление `transcripts` с `meta.processing_tier=fast`. |
| **Finalize** | JSON на `/ws/audio`: сохранить аудио, финальный fast-снимок, поставить **final** ASR. |

---

## 5. Целевая архитектура

```
Расширение (запись)
  MediaRecorder --media chunk--> /ws/audio
  /ws/transcript <-- transcript_partial (часто, для UI)

Сервер (сессия WS)
  WebM → PCM (ffmpeg) → RealtimeAudioBuffer (windowed по умолчанию)
       → whisper (realtime tier) → partials в TranscriptHub
       → [каждые fast_persist_interval_s] обновление fast в БД
       → по finalize: S3 + fast (итог) + Celery final

Web UI / API
  GET /conversations/{id}?tier=fast   — черновик (обновляется по ходу)
  GET /conversations/{id}?tier=final  — канон после воркера
```

**Разделение tier’ов:**

- **Fast** — «читать сейчас», whisper, без диаризации, допускается деградация на границах окон.
- **Final** — «канон», тот же пайплайн, что upload; export по умолчанию `tier=final`.

---

## 6. Политика буферизации и ASR

### 6.1. Режим realtime

| Параметр | Рекомендуемый дефолт | Где задаётся |
|----------|----------------------|--------------|
| `realtime_mode` | **`windowed`** | per-conversation + `default_realtime_mode` в limits |
| `chunk` | оставить в `allowed_realtime_modes` для экспериментов | — |

Режим **`chunk`** не удалять из протокола; в UI расширения — не рекомендовать как основной (подпись «устаревший / низкое качество» или скрыть в «Дополнительно»).

### 6.2. Два уровня «размера куска» (доработка)

**Проблема as-is:** одно поле `chunkSizeMs` в расширении задаёт и MediaRecorder, и `client_chunk_ms` на сервере.

**Целевое состояние:**

| Поле | Назначение | Кто задаёт |
|------|------------|------------|
| `media_chunk_ms` | Период `MediaRecorder.start(timeslice)` | Клиент (расширение), 500–2000 |
| `asr_step_ms` | Шаг буфера PCM / частота ASR | Клиент → `client_chunk_ms` при создании разговора; кламп сервера |
| `max_window_ms` | Длина окна в `windowed` | **Только сервер** (`limits.yaml`) |

**Обратная совместимость (переходный период):** если передан только `chunk_ms`, использовать его и для media, и для ASR step (как сейчас). Новые поля в `POST /api/conversations` — опционально: `media_chunk_ms`, `asr_step_ms`.

### 6.3. Рекомендуемые начальные значения

| Параметр | Значение | Комментарий |
|----------|----------|-------------|
| `media_chunk_ms` | 1000 | Баланс сеть / задержка |
| `asr_step_ms` | 2000–3000 | Шаг сдвига окна |
| `max_window_ms` | 15000–20000 | Контекст whisper |
| `fast_persist_interval_s` | 10–15 | Снимок fast в БД (§7) |
| `VT_ASR_VAD_FILTER` (API) | 1 | Резка ближе к паузам |

### 6.4. Фаза 2 — overlap и merge (backlog в рамках ТЗ)

- Перекрытие окон ASR (например 1–2 с) и слияние текста по таймкодам (аналог merge upload-чанков, §17.1).
- Partials с полями `start`/`end` в `transcript_partial` (опционально) для корректного merge в UI.

---

## 7. Персистенция fast

### 7.1. Периодические снимки (новое)

Пока открыт `/ws/audio` и накоплено аудио ≥ порога:

- каждые **`fast_persist_interval_s`** (серверный конфиг, env `VT_FAST_PERSIST_INTERVAL_SECONDS`, дефолт **12**);
- **или** сразу после успешного ASR-окна, если с прошлого снимка прошло не меньше минимального интервала (антидребезг).

Действия сервера:

1. Собрать сегменты из накопленных `partial_texts` / последнего окна с **таймкодами** (не одна строка на весь файл без времени).
2. **Upsert** строки `transcripts`: `kind=asr`, `status=success`, `meta.processing_tier=fast`, `meta.source=realtime`, `meta.fast_snapshot_seq=N`.
3. Установить `conversation.active_transcript_id` на fast, **пока** final не в `success` (как §17).
4. Опционально: событие в `/ws/transcript` — `type: "fast_snapshot"` для клиентов.

**Не** ставить Celery на каждый снимок — синхронный whisper на API (как сейчас для partials).

### 7.2. Finalize (обязательно для расширения)

По [WEBSOCKET.md](./WEBSOCKET.md), клиент отправляет:

```json
{ "type": "finalize", "finalize_id": "<uuid>" }
```

Сервер (`realtime_finalize.py`):

- сохраняет аудио в S3 (если ещё нет или обновляет);
- записывает **итоговый** fast из всех partials;
- ставит **final** в `asr_final`;
- идемпотентность по `finalize_id`.

### 7.3. Отказ от дублирующего upload (расширение)

После успешного **`finalize_ack`** расширение **не** вызывает `POST /api/upload` тем же blob (или upload становится no-op, если аудио уже в S3 — серверная идемпотентность).

Исключение: **fallback** — если WS оборвался до finalize, допустим upload с `conversation_id` (только final, без fast) — документировать в PHASE_B_ACCEPTANCE.

---

## 8. Конфигурация

### 8.1. Сервер (`configs/limits.yaml` + env)

| Ключ | Тип | Дефолт | Описание |
|------|-----|--------|----------|
| `default_realtime_mode` | string | `windowed` | Если клиент не передал режим |
| `allowed_realtime_modes` | list | `chunk`, `windowed` | |
| `chunk_ms_min` / `chunk_ms_max` | int | 500 / 3000 | Кламп `asr_step_ms` |
| `media_chunk_ms_max` | int | 2000 | Кламп `media_chunk_ms` (MediaRecorder) |
| `max_window_ms` | int | 20000 | Окно windowed |
| `fast_persist_interval_s` | int | 12 | Интервал снимков fast в БД |
| `fast_persist_min_audio_s` | float | 3.0 | Мин. длительность PCM до первого снимка |

Env (пример): `VT_FAST_PERSIST_INTERVAL_SECONDS`, `VT_FAST_PERSIST_MIN_AUDIO_SECONDS`, `VT_LIMITS_CHUNK_MS_MAX`, `VT_LIMITS_MEDIA_CHUNK_MS_MAX`.

### 8.2. На разговор (`POST /api/conversations`)

| Поле | Источник (расширение) |
|------|------------------------|
| `realtime_mode` | настройки → `realtimeMode` |
| `chunk_ms` / `asr_step_ms` | `chunkSizeMs` / будущее поле |
| `media_chunk_ms` | будущее поле (опционально) |

Сервер валидирует через `_validate_client_realtime`; значения хранятся в `conversations.client_*`.

### 8.3. ASR realtime (API)

См. [MODEL_CONFIGURATION.md](./MODEL_CONFIGURATION.md):

- `VT_ASR_REALTIME_DEVICE`, `VT_ASR_REALTIME_MODEL`, `VT_ASR_REALTIME_COMPUTE_TYPE`
- отдельно от `VT_ASR_DEVICE` на GPU-воркере (GigaAM).

---

## 9. Изменения по компонентам

### 9.1. Сервер (`server/`)

| Компонент | Изменение |
|-----------|-----------|
| `app/api/ws_realtime_buffer.py` | без смены контракта; опционально overlap (фаза 2) |
| `app/api/websocket.py` | периодический вызов persist fast; таймкоды в partials; не дублировать upload-логику |
| `app/api/realtime_finalize.py` | поддержка инкрементальных fast revision / upsert; мета `fast_snapshot_seq` |
| `app/api/conversations.py` | опционально новые поля create; отдача fast при poll |
| `app/api/upload.py` | если аудио уже в S3 после finalize — не дублировать задачу final (идемпотентность) |
| `core/config.py` | `LimitsConfig`: `fast_persist_*` |
| `configs/limits.yaml` | дефолты §8.1 |
| `docker/Dockerfile.api` | nvidia-* + `LD_LIBRARY_PATH` для CUDA realtime |
| `docker/docker-compose.yml` | `LD_LIBRARY_PATH` для api; опционально profile `api-gpu` |

### 9.2. Расширение (`browser-extension/`)

| Компонент | Изменение |
|-----------|-----------|
| `recorder/recorder.ts` | перед `ws.close()` — отправить `finalize`; убрать upload после успешного finalize |
| `websocket/client.ts` | метод `sendFinalize(finalizeId)`; обработка `finalize_ack` / `finalize_error` |
| `popup/App.tsx` | дефолт `realtimeMode: "windowed"`; UI подписи; poll fast+final после Stop |
| `settings/storage.ts` | дефолты; опционально раздельные media/asr step |
| `background.ts` | передача новых полей в `POST /api/conversations` |

### 9.3. Web UI (`webui/`)

| Компонент | Изменение |
|-----------|-----------|
| `ConversationViewerPage.tsx` | при `tier=fast` и идущей записи — poll `refetch_recommended`; текст «черновик обновляется» |
| Опционально | индикатор «идёт запись» если есть метка в conversation meta |

Запись с микрофона в Web UI **без WS** по-прежнему только upload → final (вне scope, кроме будущего WS).

### 9.4. Документация и тесты

- [WEBSOCKET.md](./WEBSOCKET.md) — `fast_snapshot`, периодический persist.
- [PHASE_B_ACCEPTANCE.md](./PHASE_B_ACCEPTANCE.md) — снять пункт «finalize не реализован в расширении» после готовности.
- `scripts/audio_acceptance_report.py` — проверка fast во время потока (опционально).
- Unit: persist fast, finalize + no duplicate upload, windowed buffer.

---

## 10. Развёртывание: API realtime на GPU

Не часть бизнес-логики fast/final, но зафиксировано для эксплуатации:

1. Образ `api` с pip `nvidia-cublas-cu12`, `nvidia-cuda-runtime-cu12`, `nvidia-cuda-nvrtc-cu12`, `nvidia-cudnn-cu12`.
2. `LD_LIBRARY_PATH` к `site-packages/nvidia/*/lib`.
3. Compose: `deploy.resources.reservations.devices: nvidia` для `api` при `VT_ASR_REALTIME_DEVICE=cuda`.
4. Глобальный `VT_ASR_DEVICE=cuda` **не** применять к api без `VT_ASR_REALTIME_DEVICE` (уже в compose).
5. VRAM: учитывать конкуренцию `api` (whisper small) + `worker-gpu-unified` + vLLM на хосте.

---

## 11. Поведение клиентов (сводка)

| Сценарий | Fast в БД | Final |
|----------|-----------|-------|
| Расширение, запись + finalize | Да (по ходу + итог) | Да (Celery) |
| Расширение, обрыв WS + upload fallback | Нет / частично | Да |
| Web UI / CLI upload файла | Нет | Да |
| WS тест `audio_acceptance_report.py` | Да | Да |

---

## 12. Критерии приёмки

### 12.1. Качество live

- [ ] Дефолт расширения и сервера — **`windowed`**.
- [ ] При записи 60 с связной речи доля «обрезанных» слов на границах **визуально ниже**, чем в режиме `chunk` 1000 ms (ручное сравнение на одном эталонном скрипте).
- [ ] В логах API нет массовых `transcribe_chunk failed` при нормальной конфигурации CUDA/CPU.

### 12.2. Fast в Web UI

- [ ] Через **10–15 с** после начала записи (расширение) `GET /api/conversations/{id}?tier=fast` возвращает **непустой** `transcript`.
- [ ] Во время записи черновик **обновляется** (revision или содержимое) без Stop.
- [ ] После Stop и finalize fast остаётся доступен; final появляется позже и переключается в `auto` по §17.

### 12.3. Finalize и upload

- [ ] Расширение при Stop отправляет **`finalize`** и получает **`finalize_ack`**.
- [ ] После успешного finalize **нет** второй постановки final из upload того же файла.
- [ ] Повторный finalize с тем же `finalize_id` → `status: duplicate`.

### 12.4. Регрессия

- [ ] Upload файла из Web UI / CLI без изменений (только final).
- [ ] Export `tier=final` — канон.
- [ ] `scripts/audio_acceptance_report.py --realtime-webm` проходит fast **и** final.

---

## 13. Этапы реализации

| Этап | Содержание | Приоритет |
|------|------------|-----------|
| **R1** | Дефолт `windowed`; finalize в расширении; отключить дублирующий upload; fast только при finalize | P0 |
| **R2** | `fast_persist_interval_s`; upsert fast по ходу; Web UI poll fast | P0 |
| **R3** | Разделение `media_chunk_ms` / `asr_step_ms`; OpenAPI + create conversation | P1 |
| **R4** | Overlap окон + merge по таймкодам; `fast_snapshot` WS event | P2 |
| **R5** | Compose profile `api-gpu`; документация VRAM | P1 (ops) |
| **R6** | Опционально: fast через Celery `asr_fast` при перегрузке API | P3 |

---

## 14. Риски

| Риск | Митигация |
|------|-----------|
| Нагрузка API при частом persist | интервал 10–15 с; один whisper на инстанс; лимит concurrency WS |
| Две final-задачи (finalize + upload) | идемпотентность upload; тесты |
| Большой образ api (nvidia-*) | только runtime libs; CPU-деплой без GPU passthrough |
| Конкуренция VRAM api + worker + vLLM | документация; `gpu-memory-utilization` для vLLM |

---

## 15. Связанные документы

- [TECHNICAL_SPECIFICATION.md §17](./TECHNICAL_SPECIFICATION.md) — канон fast/final
- [WEBSOCKET.md](./WEBSOCKET.md) — finalize, partials
- [BROWSER_EXTENSION_UI.md](./BROWSER_EXTENSION_UI.md) — UX расширения
- [PHASE_B_ACCEPTANCE.md](./PHASE_B_ACCEPTANCE.md) — чеклист приёмки
- [MODEL_CONFIGURATION.md](./MODEL_CONFIGURATION.md) — realtime vs final providers

---

## 16. История версий

| Версия | Дата | Изменение |
|--------|------|-----------|
| 1.1 | 2026-06-30 | Реализация R1–R6 (v0.3.2): finalize, persist fast, media/asr step, overlap, api-gpu override |
