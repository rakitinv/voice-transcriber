# GigaAM ASR-провайдер

Канон конфигурации: [`MODEL_CONFIGURATION.md`](./MODEL_CONFIGURATION.md), [`configs/asr.yaml`](../configs/asr.yaml).

## Назначение

**GigaAM** ([salute-developers/GigaAM](https://github.com/salute-developers/GigaAM)) — ASR для **русской речи**. В voice-transcriber подключается как провайдер `gigaam` в едином registry (`app/asr/factory.py`, `plugins/loader.py`).

Рекомендуемая модель: **`v3_e2e_rnnt`** (пунктуация и нормализация текста).

## Где используется

| Режим | Путь | Провайдер |
|-------|------|-----------|
| **Realtime** | `core/asr_chunk.py`, `/ws/audio` | `realtime_provider` → fallback `default_provider` |
| **Final / batch** | `workers/tasks/asr.py` | `final_provider` → fallback `default_provider` |
| Diarization re-ASR | `workers/tasks/diarization.py` | `final_provider` (как batch) |

**По умолчанию в репозитории** `gigaam` в `asr.yaml` **выключен** (`enabled: false`). Whisper/faster-whisper остаются дефолтом для API и dev.

## Конфигурация

### `configs/asr.yaml`

```yaml
default_provider: whisper
realtime_provider: whisper
final_provider: gigaam
final_recognition_model: v3_e2e_rnnt
recognition_model: medium   # для whisper (realtime tier)

providers:
  gigaam:
    enabled: false
    model: v3_e2e_rnnt
    longform_enabled: true
    hf_token_env: VT_HF_TOKEN
    model_cache_dir: /models
```

### Переменные окружения

| Переменная | Назначение |
|------------|------------|
| `VT_ASR_REALTIME_PROVIDER` | Движок для realtime (API) |
| `VT_ASR_FINAL_PROVIDER` | Движок для final (Celery) |
| `VT_ASR_REALTIME_MODEL` / `VT_ASR_FINAL_MODEL` | Модели по tier |
| `VT_ASR_DEFAULT_PROVIDER` | Fallback для обоих tier |
| `VT_ASR_MODEL` | Модель для `default_provider` (legacy) |
| `VT_ASR_DEVICE` | `cpu` / `cuda` |
| `VT_GIGAAM_LONGFORM` | `1` — для файлов >24 с вызывать `transcribe_longform` (нужен HF token и extra `longform`) |
| `VT_GIGAAM_CHUNK_SECONDS` | Fallback-нарезка без longform (по умолчанию `20`) |
| `VT_HF_TOKEN` | Для longform (pyannote segmentation внутри GigaAM) |
| `HF_HOME` / volume `/models` | Кэш весов Hugging Face |

## Длинные файлы

1. **≤24 с** — `model.transcribe(wav)`.
2. **`VT_GIGAAM_LONGFORM=1`** и установлен extra `[longform]` — `model.transcribe_longform(wav)` (сегменты с таймингами).
3. Иначе — нарезка ffmpeg на окна ~20 с с перекрытием, `transcribe` на каждый клип.

Параллельная нарезка Celery (`VT_ASR_PARALLEL_CHUNKS`) по-прежнему работает: каждый слайс должен обрабатываться провайдером независимо.

## Docker

Образ **`worker-final-gpu`** (`docker/Dockerfile.worker.gpu`): `poetry install --with gigaam`.

Пример включения на GPU-воркере:

```bash
# Опционально через env (иначе достаточно asr.yaml):
# VT_ASR_FINAL_PROVIDER=gigaam
# VT_ASR_FINAL_MODEL=v3_e2e_rnnt
VT_ASR_DEVICE=cuda
VT_GIGAAM_LONGFORM=1
VT_HF_TOKEN=hf_...
```

API и лёгкий `worker` **без** группы `gigaam` — realtime остаётся на faster-whisper.

Образ **diarization-worker** не объединяют с GigaAM в одном процессе (разные pin torch / VRAM). Для русского re-ASR в diarization — отдельный воркер или env на GPU-хосте.

## Ограничения

- **Только русский**; при `language=en` провайдер предупреждает в логах (распознавание всё равно идёт как для RU).
- Тяжёлые зависимости (torch, ~1.5 GB весов) — optional Poetry group `gigaam`.
- Longform внутри GigaAM использует **pyannote segmentation**, это не замена post-hoc diarization проекта.

## Тесты

- Unit: `server/tests/unit/test_gigaam_provider.py` (mock, без модели).
- Integration: маркер `asr_inference`, флаг `VT_SKIP_ASR_INFERENCE=1`, отдельный русский fixture (по мере появления).

## Ссылки

- [GigaAM README](https://github.com/salute-developers/GigaAM/blob/main/README.md)
- [ASR_PROVIDER_IMPLEMENTATION.md](./ASR_PROVIDER_IMPLEMENTATION.md)
