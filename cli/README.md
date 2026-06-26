# Voice Transcriber CLI (`cli/`)

Устанавливаемый пакет **`voice-transcriber-cli`** с консольной командой **`transcriber`**. Использует тот же REST API, что **Web UI** и `scripts/phase_a_upload_smoke.py`: заголовок **`Authorization: Bearer <JWT>`** или **`X-VT-Api-Key: <secret>`**, **`POST /api/upload`** с multipart-полем **`file`**.

## Установка

Из корня репозитория:

```bash
cd cli
pip install -e .
```

Требуется **Python 3.12+** и зависимость **httpx** (прописана в `pyproject.toml`).

## Аутентификация (JWT или API key)

- JWT: переменная окружения **`VT_ACCESS_TOKEN`**, или флаг **`--token`**.
- JWT из **Web UI**: `localStorage` → ключ **`access_token`** (три части через точку), не cookie `token`.
- Нормализация: можно вставить фрагмент URL с `#access_token=...` — CLI отрежет лишнее (как в smoke-скрипте).
- API key (Phase C6): переменная окружения **`VT_API_KEY`** или флаг **`--api-key`** (сервер проверяет заголовок **`X-VT-Api-Key`**).
  - Выдача ключа администратором: `scripts/issue_api_key.py` (печатает секрет один раз; в БД хранится только SHA-256).

## Глобальные опции

| Опция | Env | По умолчанию |
|-------|-----|----------------|
| `--base-url` | `VT_API_BASE_URL` | `http://127.0.0.1:8002` |
| `--token` | `VT_ACCESS_TOKEN` | (пусто) |
| `--api-key` | `VT_API_KEY` | (пусто) |
| `--timeout` | — | `120` |

Нужно задать **одно из двух**: `--token`/`VT_ACCESS_TOKEN` **или** `--api-key`/`VT_API_KEY`.

Пример:

```bash
set VT_ACCESS_TOKEN=eyJ...
transcriber --base-url http://127.0.0.1:8002 me
```

## Команды

### `transcriber me`

`GET /api/auth/me` — текущий пользователь. Флаг **`--json`** — сырой JSON.

### `transcriber upload [FILE]`

`POST /api/upload`.

- **`FILE`** — локальный аудиофайл; если не указан, отправляется встроенная заглушка (webm или mp3 при `--audio-format mp3`).
- **`--audio-format`** — query `audio_format` (расширение без точки). Env: `VT_UPLOAD_AUDIO_FORMAT`.
- **`--conversation-id`** — привязка к существующему разговору (UUID).
- По умолчанию после **202** CLI **опрашивает** `GET /api/conversations/{id}` до появления сегментов в `transcript` (как smoke-скрипт).
- **`--no-wait`** — только ответ upload, без опроса.
- **`--interval`**, **`--max-wait`** — параметры опроса (секунды).
- **`--quiet`** — меньше сообщений в stderr при опросе.
- Если `--max-wait` истёк: код выхода **124** (timeout).

### `transcriber conversations list`

`GET /api/conversations` — опции **`--skip`**, **`--limit`**, **`--json`**.

### `transcriber conversations create`

`POST /api/conversations` — создать разговор. Полезно для §7-цепочек (поля `previous_conversation_id` / `recording_session_id`).

Флаги: `--title`, `--ttl-days`, `--realtime-mode chunk|windowed`, `--chunk-ms`, `--previous-conversation-id`, `--recording-session-id`, `--json`.

### `transcriber conversations chain <recording_session_id>`

`GET /api/conversations?recording_session_id=...` — показать цепочку автопродления (§7) для одной сессии записи.

### `transcriber conversations show <UUID>`

`GET /api/conversations/{id}` — по умолчанию красивый JSON; **`--json`** то же самое (единообразие с `me`).

### `transcriber export <UUID> --format md|json`

`GET /api/conversations/{id}/export?format=...`

- **`-o` / `--output`** — файл; без него тело пишется в **stdout** (бинарно/текстом в зависимости от формата).

### `transcriber audio <UUID> [-o PATH]`

`GET /api/conversations/{id}/audio` — исходное аудио из хранилища.

- Без **`-o`** имя файла берётся из **`Content-Disposition`**, иначе `recording-<id>.bin`.

### `transcriber delete <UUID>`

`DELETE /api/conversations/{id}`.

## Запуск как модуль

```bash
python -m voice_transcriber_cli --help
```

## Связь со smoke-скриптом

`scripts/phase_a_upload_smoke.py` остаётся автономным однофайловым сценарием. Для интерактивной работы предпочтительна команда **`transcriber`** (те же env, расширенный набор подкоманд).

## Паритет с Web UI

| Действие | Web UI | CLI |
|----------|--------|-----|
| Загрузка файла | Кнопка на списке разговоров | `transcriber upload path.wav` |
| Список / просмотр | Страницы | `conversations list`, `conversations show` |
| Экспорт транскрипта | Кнопка Download | `transcriber export …` |
| Исходное аудио | Иконка микрофона | `transcriber audio …` |

Повторный **batch ASR** по уже загруженному аудио (**Transcribe again** в Web UI) и повтор **diarization** (**Diarize again**) — эндпоинты **`POST /api/conversations/{id}/retranscribe`** и **`POST …/diarize`** в **`openapi.yaml`**; отдельных подкоманд `transcriber` под них пока нет (достаточно `curl` с тем же JWT).

Подробности контракта — **`openapi.yaml`**, **`server/app/api/upload.py`**.
