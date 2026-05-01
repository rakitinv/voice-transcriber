# WebSocket — контракт (Phase B)

Канон постановки: [TECHNICAL_SPECIFICATION.md](./TECHNICAL_SPECIFICATION.md) §3.3, §4.  
HTTP API остаётся под префиксом **`/api`** (все клиенты: Web UI, CLI, расширение).  
Каналы **realtime** — под префиксом **`/ws`** (тот же хост и origin, что и REST).

## URL

| Назначение | Путь | Протокол |
|------------|------|----------|
| Поток аудио-чанков | `/ws/audio/{conversation_id}` | WebSocket |
| Поток обновлений транскрипта | `/ws/transcript/{conversation_id}` | WebSocket |

`conversation_id` — UUID существующего разговора.

Примеры (локально, API на порту 8002):

- `ws://127.0.0.1:8002/ws/audio/<uuid>`
- `ws://127.0.0.1:8002/ws/transcript/<uuid>`

В проде при HTTPS: **`wss://<host>/ws/...`** (тот же хост, что и `https://<host>/api/...`).

## Порядок использования

1. Создать разговор: **`POST /api/conversations`** (или использовать уже созданный).
2. Открыть нужные WebSocket-соединения с тем же `conversation_id`.
3. Передавать JWT (см. ниже).

Два сокета независимы: клиент может открыть только аудио, только транскрипт, или оба.

## Аутентификация (Phase B MVP)

Используется **тот же access token (JWT)**, что и для REST (`Authorization: Bearer`).

Поддерживаются **два** способа передачи токена при установке соединения. В **production** (`VT_ENVIRONMENT=production`, см. конфиг) параметр query **`access_token` запрещён** — принимается только **subprotocol** `bearer.<JWT>` (закрытие handshake до accept с кодом **1008**, причина `query_token_forbidden`). Для dev/скриптов можно включить query обратно: **`VT_WS_ALLOW_QUERY_TOKEN=1`**. Явно потребовать только subprotocol в любом окружении: **`VT_WS_REQUIRE_SUBPROTOCOL=1`**.

### 1) Query-параметр

```
ws://host/ws/audio/<uuid>?access_token=<JWT>
```

### 2) Заголовок `Sec-WebSocket-Protocol`

Клиент передаёт один из элементов списка протоколов в виде:

```
bearer.<JWT>
```

то есть строка начинается с `bearer.` (регистр не важен при разборе), далее **целиком** JWT (три части через точку). Пример второго аргумента конструктора в браузере:

```javascript
const proto = "bearer." + accessToken;
new WebSocket(url, [proto]);
```

Сервер принимает соединение с выбранным подпротоколом (эхо согласованного значения в handshake).

**Приоритет разбора на сервере (не strict):** если задан непустой `access_token` в query — он используется; иначе ищется элемент вида `bearer.<JWT>` в `Sec-WebSocket-Protocol`. В strict-режиме непустой query-токен всегда отклоняется.

## Авторизация

После проверки подписи JWT сервер убеждается, что:

- пользователь с `sub` из токена существует;
- разговор `conversation_id` принадлежит этому пользователю;
- `deleted_at` разговора пустой.

При ошибке аутентификации или доступа соединение закрывается (см. реализацию; рекомендуемый код — `1008` Policy Violation для отказа по политике).

## Сообщения (Phase B)

### Канал `/ws/audio/{conversation_id}`

- После установления соединения: JSON **`type: "ready"`**, поля `realtime_mode`, `chunk_ms`, `conversation_id`, **`pcm_pipeline`** (bool: декод WebM→PCM через ffmpeg).
- Клиент отправляет **бинарные** фреймы (фрагменты WebM/Opus, как от `MediaRecorder`).
- Если **`pcm_pipeline: true`**: ffmpeg декодирует поток в **PCM s16le mono 16 kHz**; режимы **chunk** / **windowed** применяются к **PCM** по времени (`chunk_ms`, `max_window_ms` из limits и разговора).
- Если ffmpeg недоступен или задано **`VT_DISABLE_WEBM_DECODE=1`**: **legacy** — буфер по оценке байт/с по сырому контейнеру (грубее по времени).
- После каждого срабатывания порога ASR: JSON **`type: "asr_ok"`** (`bytes_ingested`, `text_len`, `pcm`); при ошибке декодера — `stage: "decode"`, при ASR — `stage: "asr"`.
- Текстовые фреймы (JSON): опционально; ответ **`type: "ack_text"`** с эхом.

Частичный текст распознавания уходит в канал **transcript** (см. ниже), не дублируется обязательно в `audio`.

### Канал `/ws/transcript/{conversation_id}`

- После **`ready`** сервер пушит JSON с **`type: "transcript_partial"`**, поля `text`, `conversation_id`, `realtime_mode`, опционально **`pcm`** (совпадает с пайплайном audio).
- При отсутствии событий до 60 с — **`type: "keepalive"`** (можно изменить при интеграции клиента).

**Несколько инстансов API:** задайте **`VT_TRANSCRIPT_REDIS=1`** и доступный Redis (`VT_REDIS_URL` / `configs/server.yaml`); публикация частичных транскриптов идёт в Redis pub/sub (канал `transcript:<conversation_id>`). Без флага — in-memory внутри процесса.

## Команда `finalize` (ТЗ §17)

Канон постановки: [TECHNICAL_SPECIFICATION.md §17](./TECHNICAL_SPECIFICATION.md).

На канале **`/ws/audio/{conversation_id}`** клиент может отправить **текстовый** JSON-фрейм (не бинарный):

```json
{ "type": "finalize", "finalize_id": "<uuid или произвольная непустая строка>" }
```

Требуется накопленное за сессию аудио (PCM или сырой контейнер) не короче внутреннего порога; иначе **`finalize_error`** с `detail`: **`insufficient_audio`**.

Сервер отвечает JSON:

- при успехе: `{ "type": "finalize_ack", "conversation_id": "<uuid>", "finalize_id": "...", "status": "accepted" }` — аудио сохранено в S3, в БД создан **`transcripts`** с **`meta.processing_tier=fast`**, **`active_transcript_id`** указывает на него; в Celery поставлена задача **`transcribe_file`** для ветки **final** (`meta.processing_tier=final` после успеха воркера);
- повтор с тем же `finalize_id` (идемпотентность): `"status": "duplicate"` (Redis SET NX при **`VT_REDIS_URL`**; TTL 7 суток);
- ошибки: `finalize_id is required`, `insufficient_audio`, `conversation_not_found`, `server_error` и др.

События **`transcript_partial`** в hub содержат **`processing_tier": "fast"`** (realtime).

REST: **`GET /api/conversations/{id}?tier=fast|final|auto`** и **`GET .../export?format=...&tier=...`** — см. `openapi.yaml`.

## Автопродление §7 (Phase C3)

При **`limits.autoprolong_enabled: true`** в `configs/limits.yaml` (или переменные окружения, см. `LimitsConfig`) сервер отслеживает накопленный realtime-поток на канале **`/ws/audio/{id}`**:

- **duration:** оценка по PCM **16 kHz mono s16le** (`байты_PCM / 32000` секунд) против **`limits.max_duration_seconds`**;
- **size:** накопиченный сырой контейнер (**байты**) против **`limits.max_file_size_bytes`**.

При первом срабатывании (что наступит раньше — см. ТЗ §7.2):

1. Если аудио не проходит внутренний порог финализации — сообщение **`autoprolong_error`** с `detail`: **`insufficient_audio_for_rotate`**.
2. Иначе сервер выполняет тот же путь, что и клиентский **`finalize`** (сохранение в S3, fast-транскрипт, постановка final ASR в Celery), с искусственным **`finalize_id`** вида `autoprolong-<uuid>`.
3. Создаётся новый разговор **B** с тем же **`recording_session_id`**, **`previous_conversation_id`** = A, теми же **realtime** полями (`client_realtime_mode`, `client_chunk_ms`).
4. Клиенту отправляется JSON и соединение закрывается нормально (`close 1000`):

```json
{
  "type": "autoprolong_handoff",
  "conversation_id": "<uuid A>",
  "finalize_id": "autoprolong-<uuid>",
  "reason": "duration|size",
  "next_conversation_id": "<uuid B>",
  "recording_session_id": "<uuid сессии>",
  "previous_conversation_id": "<uuid A>"
}
```

Клиент должен открыть **новый** WebSocket **`/ws/audio/{next_conversation_id}`** (и при необходимости **`/ws/transcript/...`**) и продолжить передачу чанков. Догрузка «хвоста» в A уже включена в буфер на момент автоматического `finalize` (§7.5).

При ошибке финализации или создании B: **`autoprolong_error`** с полем **`detail`** (и **`reason`**).

## Phase C7.5 (выполнено)

- Политика JWT для WS в prod: только **subprotocol**, без query (переменные **`VT_WS_REQUIRE_SUBPROTOCOL`**, **`VT_WS_ALLOW_QUERY_TOKEN`** — см. выше).

## Будущее (Phase C / hardening)

- Отдельный **короткоживущий токен** только для WebSocket (выдача через REST), вместо длинного JWT в subprotocol.
- Уточнение политики логирования и отзыва сессий.

## OpenAPI

В `openapi.yaml` для путей `/ws/...` добавлены описательные заглушки (OAS 3 не описывает WebSocket полноценно); канон сообщений (**в т.ч. `finalize`**) — в этом документе. Чеклист §17.11 в ТЗ согласован с этим ([TECHNICAL_SPECIFICATION.md §17.11](./TECHNICAL_SPECIFICATION.md)).
