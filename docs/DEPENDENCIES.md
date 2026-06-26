# Зависимости сервера (канон)

Краткая справка по версиям и пересборке lock. Полный план миграции: [DEPENDENCIES_MIGRATION.md](./DEPENDENCIES_MIGRATION.md).

## Базовая линия

| Параметр | Значение |
|----------|----------|
| Python | **3.12** (`>=3.12,<3.15` в `server/pyproject.toml`; образы `python:3.12-slim`) |
| Менеджер зависимостей | Poetry 2.x |
| numpy | `>=2.1,<3` |
| onnxruntime | `>=1.23,<2` (lock: **1.23.2** — требование GigaAM) |
| huggingface-hub | `^1.0` (main + optional groups) |
| ASR (main) | faster-whisper, vosk |
| Diarization (group) | pyannote-audio **4.x**, torch/torchaudio **2.10** |
| GigaAM (group) | `gigaam[longform]` из Git, torch **2.10** |

## Группы Poetry

```bash
cd server
poetry install --only main          # API, worker CPU
poetry install --with diarization   # diarization-worker
poetry install --with gigaam        # worker-final-gpu
poetry install --with dev           # pytest, ruff (образ tests)
```

## Пересборка `poetry.lock` (на Python 3.12)

Нужен **git** (зависимость GigaAM из GitHub):

```bash
docker run --rm -v "$(pwd)/server:/app/server" -w /app/server python:3.12-slim bash -c \
  "apt-get update -qq && apt-get install -y -qq git && pip install poetry==2.3.2 && \
   poetry config virtualenvs.create false && poetry lock"
```

PowerShell:

```powershell
docker run --rm -v "${PWD}/server:/app/server" -w /app/server python:3.12-slim bash -c `
  "apt-get update -qq && apt-get install -y -qq git && pip install poetry==2.3.2 && poetry config virtualenvs.create false && poetry lock"
```

## Torch в Docker (`install-torch.sh`)

Скрипт: [`docker/scripts/install-torch.sh`](../docker/scripts/install-torch.sh). Большие загрузки — через [`pip-retry.sh`](../docker/scripts/pip-retry.sh) (повторы при обрыве сети / сне ПК).

| Образ | База | Torch |
|-------|------|-------|
| **`ml-base-cpu`** | `Dockerfile.ml-base` target `ml-base-cpu` | `install-torch.sh cpu` |
| **`ml-base-cuda`** | `Dockerfile.ml-base` target `ml-base-cuda` | `install-torch.sh cuda` |
| `diarization-worker` | `FROM ml-base-cpu` | (в base) |
| `diarization-worker-gpu` | `FROM ml-base-cuda` | (в base) |
| `worker-final-gpu` | `FROM ml-base-cuda` | (в base) |

### Образы ML base

Файл: [`docker/Dockerfile.ml-base`](../docker/Dockerfile.ml-base). Содержит Poetry **main + diarization + gigaam** (gigaam через `poetry export` без повторного torch) и один вызов **`install-torch.sh`**.

Локальные теги (compose): `voice-transcriber-ml-base-cpu:${ML_BASE_TAG:-local}`, `voice-transcriber-ml-base-cuda:${ML_BASE_TAG:-local}`.

```bash
cd docker
# только base (редко — при смене lock / torch)
docker compose --profile ml-base build ml-base-cpu ml-base-cuda

# GPU child (targets в Dockerfile.ml-base; ml-base-cuda собирается один раз на оба сервиса)
docker compose --profile gpu build worker-final-gpu diarization-worker-gpu
```

**Когда пересобирать base vs child**

| Изменилось | Действие |
|------------|----------|
| `server/pyproject.toml`, `poetry.lock`, `Dockerfile.ml-base`, `install-torch.sh` | `ml-base-cpu` / `ml-base-cuda`, затем child |
| Только код в `server/` (без lock) | `docker compose build worker-final-gpu` или `diarization-worker-gpu` |
| Registry на площадке | `push-registry.sh` пушит `vt-ml-base-{cpu,cuda}:${TORCH_VERSION}-{variant}-${TAG}`; child-образы тянут общий слой при pull base |

Build-args child-образов: **`ML_BASE_IMAGE`** (по умолчанию локальный тег выше). На площадке можно задать registry-тег base и пересобрать только thin layer.

### Пересборка после сбоя сети

**Полный `build-docker.bat` не обязателен.** Docker кэширует успешные слои; перезапускайте только упавший сервис:

```bash
cd docker
docker compose build worker-final-gpu
```

Windows:

```bat
cd docker
docker compose build worker-final-gpu
```

или `scripts\release\build-docker.bat worker-final-gpu`

Кэш pip (`--mount=type=cache`) сохраняет частично скачанные wheels между попытками.

Build-args (общие):

| Arg | По умолчанию | Назначение |
|-----|--------------|------------|
| `DIARIZATION_TORCH` | `cpu` | `cpu` или `cuda` (только diarization Dockerfile) |
| `TORCH_VERSION` | `2.10.0` | Версия wheel (`TORCH_VERSION` env для скрипта) |

Индексы: CPU — `download.pytorch.org/whl/cpu`, CUDA — `whl/cu128`.

## Docker-образы и дублирование слоёв

Образы **`ml-base-cpu`** / **`ml-base-cuda`** выносят Poetry + torch в общий parent. **`worker-final-gpu`** и **`diarization-worker-gpu`** — тонкие child (`FROM ml-base-cuda`); на диске и в registry слой torch хранится один раз.

## Unit-тесты

```bash
cd docker
docker compose build tests
docker compose run --rm tests
```

См. [TESTING.md](./TESTING.md), [docker/README.md](../docker/README.md).
