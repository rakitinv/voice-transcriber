# Настройка и подключение моделей (ASR / diarization / embeddings / LLM)

Этот документ фиксирует **где** и **как** настраиваются модели/провайдеры в репозитории.
Канон API/WS: [`openapi.yaml`](../openapi.yaml), [`WEBSOCKET.md`](./WEBSOCKET.md).

## Быстрые ссылки (что где задаётся)

| Назначение | Файл конфигурации | Где используется |
|-----------|--------------------|------------------|
| **ASR** (whisper / faster-whisper / vosk…) | [`configs/asr.yaml`](../configs/asr.yaml) | batch: `workers/tasks/asr.py`, realtime: `core/asr_chunk.py`, factory: `app/asr/factory.py` |
| **Diarization** (pyannote и др.) | [`configs/diarization.yaml`](../configs/diarization.yaml) | `workers/tasks/diarization.py` |
| **Embeddings** (семантический поиск) | [`configs/embeddings.yaml`](../configs/embeddings.yaml) | `workers/tasks/embeddings.py`, `app/api/search.py`, `core/embedding_client.py` |
| **LLM** (summary и др.) | [`configs/llm.yaml`](../configs/llm.yaml) | `workers/tasks/llm.py`, `plugins/` |
| **Лимиты realtime/автопродление** | [`configs/limits.yaml`](../configs/limits.yaml) | `app/api/websocket.py`, `GET /api/settings/limits` |

## ASR (распознавание речи)

### Где настраивается
- [`configs/asr.yaml`](../configs/asr.yaml):
  - `default_provider`: активный движок по умолчанию
  - `recognition_model`: модель для `default_provider` (перекрывает `providers.<name>.model`)
  - `providers.*`: включение/пути/реализация (например Vosk `model_path`)

### Переопределения окружением (удобно для Docker)
- `VT_ASR_DEFAULT_PROVIDER`
- `VT_ASR_MODEL`

См. также: [`ASR_PROVIDER_IMPLEMENTATION.md`](./ASR_PROVIDER_IMPLEMENTATION.md), [`docker/README.md`](../docker/README.md).

## Diarization (спикеры)

### Где настраивается
- [`configs/diarization.yaml`](../configs/diarization.yaml):
  - `enabled`: включает постановку задачи diarization после успешного ASR
  - `default_provider` / `providers.*`
  - `turn_level_retranscription`: политика «перераспознавать по turn или только назначать спикеров»

См. канон поведения и версионирования: [`DIARIZATION_ALIGNMENT_VERSIONING.md`](./DIARIZATION_ALIGNMENT_VERSIONING.md).

### Важно про CPU/GPU
CPU/CUDA колёса PyTorch выбираются **на этапе сборки образа** diarization-worker (см. [`docker/README.md`](../docker/README.md)),
а не переключением одной строкой в `configs/diarization.yaml`.

## Embeddings (семантический поиск C2)

### Где настраивается
- [`configs/embeddings.yaml`](../configs/embeddings.yaml) — по умолчанию `enabled: false`.

Ключевые поля:
- `enabled`: включает индексацию эмбеддингов и режим `GET /api/search?mode=semantic`
- `provider`: `ollama` или `openai`
- `model`: имя модели эмбеддингов (например `nomic-embed-text`)
- `base_url`: для Ollama
- `openai_base_url`, `openai_api_key`: для OpenAI-compatible

### Переменные окружения
- `VT_EMBEDDINGS_ENABLED=1|0`
- `VT_EMBEDDINGS_PROVIDER`, `VT_EMBEDDINGS_MODEL`
- `VT_OLLAMA_EMBEDDINGS_URL`
- `VT_OPENAI_API_KEY` или `OPENAI_API_KEY`

### Как это работает в коде
- При успешном ASR/diarization после promote активной версии ставится Celery задача
  `workers.tasks.embeddings.index_transcript_embedding` (очередь `llm`).
- Запрос `GET /api/search?mode=semantic` в рантайме строит embedding запроса и считает cosine similarity по сохранённым векторам.

## LLM (summary и др.)

### Где настраивается
- [`configs/llm.yaml`](../configs/llm.yaml): `default_provider`, `providers.*`, **`session_summary_enabled`**, **`session_summary_max_input_chars`** (ТЗ §7.6), опционально **`VT_LLM_SESSION_SUMMARY_ENABLED`**, **`VT_LLM_SESSION_SUMMARY_MAX_INPUT_CHARS`** в окружении API/воркера.

Задачи: `workers/tasks/llm.py` (провайдер выбирается через `plugins/` registry). Реализован провайдер **`ollama`**; rolling summary цепочки — задача **`summarize_recording_session`** (очередь **`llm`**).

## Автопродление (§7) — что настраивается

- Включение и «хвост» задаются через [`configs/limits.yaml`](../configs/limits.yaml):
  - `autoprolong_enabled`
  - `autoprolong_tail_seconds`
  - а также лимиты `max_duration_seconds` / `max_file_size_bytes` (триггер §7.2).

Протокол сообщений при ротации описан в [`WEBSOCKET.md`](./WEBSOCKET.md) (раздел «Автопродление §7»).

