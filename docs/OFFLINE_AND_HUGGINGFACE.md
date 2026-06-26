# Локальный стек и модели Hugging Face

`localhost` в `docker/.env` (API **8002**, Web UI **3002**, Admin **3003**) описывает **сервисы приложения** на вашей машине. Это не означает, что все **веса ML-моделей** уже лежат внутри образов.

При первом запуске этапов пайплайна воркеры обычно **один раз** обращаются в интернет (чаще всего на [huggingface.co](https://huggingface.co)), скачивают артефакты и кладут их в **кэш** (Docker volume или каталог в контейнере). Дальше inference идёт **локально** в контейнере, без облачного API распознавания.

Связанные документы: [docker/README.md](../docker/README.md) (compose, offline diarization), [MODEL_CONFIGURATION.md](./MODEL_CONFIGURATION.md), [GIGAAM_ASR.md](./GIGAAM_ASR.md), [DIARIZATION_ALIGNMENT_VERSIONING.md](./DIARIZATION_ALIGNMENT_VERSIONING.md).

---

## Что локально, что с Hugging Face

| Компонент | Где выполняется inference | Откуда берутся веса (первый раз) | Кэш по умолчанию | Нужен `VT_HF_TOKEN` |
|-----------|---------------------------|----------------------------------|------------------|---------------------|
| **API, БД, S3, очереди** | контейнеры compose | образы Docker / MinIO на диске | тома `postgres-data`, `minio-data`, … | нет |
| **ASR final** (`whisper` / `faster-whisper`) | `worker-final` | Hugging Face (репозитории faster-whisper, напр. `Systran/faster-whisper-medium`) | кэш внутри контейнера воркера | обычно **нет** |
| **ASR final** (`gigaam`) | `worker-final-gpu` | Git (пакет) + HF для весов; longform — segmentation pyannote | volume `gigaam-models` → `/models` | **да** (longform) |
| **Diarization** (`pyannote`) | `diarization-worker` | Hugging Face, gated-модели pyannote | volume `diarization-models` → `/models` | **да** |
| **LLM-сводка** | `worker` | **не HF** — Ollama на хосте (`VT_OLLAMA_BASE_URL`) | у Ollama на машине | нет |
| **Embeddings** | `worker` | Ollama или OpenAI-compatible (см. `configs/embeddings.yaml`) | зависит от провайдера | опционально |

Токен **`VT_HF_TOKEN`** в `docker/.env` — это **ключ доступа** к gated-репозиториям HF для аккаунта, который **принял условия** моделей на сайте. Это не URL сервиса.

---

## Diarization (pyannote 4.x): что принять на Hugging Face

Перед первой диаризацией (или прогревом кэша) войдите на [huggingface.co](https://huggingface.co) под тем же аккаунтом, для которого создан токен, и нажмите **Agree and access** на страницах:

| Репозиторий | Зачем |
|-------------|--------|
| [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) | пайплайн pyannote.audio 4.x (зависимость; без согласия — **403**) |
| [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) | указан в `configs/diarization.yaml` как `model` |
| [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) | зависимость пайплайна |

Создайте токен с правом **Read**: [hf.co/settings/tokens](https://huggingface.co/settings/tokens). Для fine-grained токена включите доступ к **gated public repositories**.

В `docker/.env`:

```env
VT_HF_TOKEN=hf_...
```

В compose для diarization-воркера токен пробрасывается в `VT_HF_TOKEN`, `HF_TOKEN`, `HUGGINGFACE_HUB_TOKEN` (см. `docker-compose.yml`).

Конфиг: [`configs/diarization.yaml`](../configs/diarization.yaml) — `model_cache_dir: /models`, `offline_models: false` (по умолчанию разрешена загрузка из сети).

### Проверка доступа из контейнера

```bash
cd docker
docker compose exec -T diarization-worker python -c "
import os
from huggingface_hub import hf_hub_download
hf_hub_download(
    'pyannote/speaker-diarization-community-1',
    'plda/xvec_transform.npz',
    token=os.environ['HF_TOKEN'],
)
print('HF access OK')
"
```

Ожидается `HF access OK` без `403 Forbidden`.

---

## Прогрев кэша diarization (один раз, с сетью)

Подробный пошаговый сценарий (online → warmup → `offline_models: true`): раздел **«Diarization: offline models»** в [docker/README.md](../docker/README.md#diarization-offline-models-pyannote--прогрев-кэша).

Кратко:

1. `offline_models: false`, `VT_HF_TOKEN` задан, условия HF приняты.
2. Поднять воркер: `docker compose --profile diarization up -d diarization-worker`
3. Прогреть без разговора:

   ```bash
   docker compose --profile diarization run --rm diarization-worker python -m app.diarization.warmup
   ```

   Либо выполнить diarization на любом разговоре (Web UI **Diarize again**).

4. Убедиться, что volume `diarization-models` не пустой (модели остаются между перезапусками compose).
5. Для **строго офлайн** после прогрева: `offline_models: true` в `configs/diarization.yaml`, перезапуск воркера. Токен можно не задавать, если все файлы уже в `/models`.

Опционально при старте: `VT_DIARIZATION_WARMUP=1` — self-check до запуска Celery (см. docker/README).

---

## ASR (whisper / faster-whisper): прогрев на CPU dev-стеке

На CPU dev часто задают `VT_ASR_FINAL_PROVIDER=whisper` в `docker/.env` (перекрывает `final_provider: gigaam` в `configs/asr.yaml`). Веса faster-whisper при **первой** транскрипции скачиваются с Hugging Face автоматически; отдельного токена для публичных моделей Systran обычно не нужно.

Прогрев: один раз выполнить распознавание (загрузка файла в Web UI или `POST /api/upload`). Кэш живёт в слое контейнера `worker-final` (при `docker compose build --no-cache` или новом контейнере без сохранённого кэша загрузка повторится).

Модель задаётся `VT_ASR_FINAL_MODEL` / `VT_ASR_MODEL` / `recognition_model` в [`configs/asr.yaml`](../configs/asr.yaml) (по умолчанию `medium`).

---

## GigaAM (GPU, опционально)

Если `final_provider: gigaam` и образ `worker-final-gpu`:

- пакет `gigaam` — в образе (Poetry group `gigaam`);
- веса — HF, кэш volume `gigaam-models` → `/models`;
- longform (`VT_GIGAAM_LONGFORM=1`) дополнительно использует segmentation pyannote → нужен **`VT_HF_TOKEN`** и принятие условий pyannote (см. таблицу выше).

См. [GIGAAM_ASR.md](./GIGAAM_ASR.md).

---

## Что не относится к Hugging Face

| Настройка в `docker/.env` | Назначение |
|---------------------------|------------|
| `VT_PUBLIC_API_URL`, `VT_ADMIN_WEBUI_ORIGIN` | URL для браузера на хосте |
| `VT_OLLAMA_BASE_URL=http://host.docker.internal:11434` | LLM на **вашем ПК** (вне compose) |
| `COMPOSE_PROFILES=diarization` | какие optional-сервисы compose поднимает |
| `VT_DEPLOY_PROFILE=cpu` | метка стека для проверок совместимости в админке |

---

## Режим «только локальная сеть» (чеклист)

1. Один раз **с интернетом**: принять условия HF, задать `VT_HF_TOKEN`, прогреть diarization (`warmup` или реальная задача) и ASR (одна транскрипция).
2. При необходимости GigaAM — собрать и прогреть `worker-final-gpu`, проверить volume `gigaam-models`.
3. В `configs/diarization.yaml`: `offline_models: true`.
4. Не удалять тома `diarization-models` / `gigaam-models` без повторного прогрева.
5. LLM/embeddings: либо локальный Ollama на хосте, либо отключить фичи в конфиге.

После этого пайплайн **не вызывает облачные API** ASR/diarization; остаются только ваши контейнеры, MinIO и (если включено) Ollama на машине.
