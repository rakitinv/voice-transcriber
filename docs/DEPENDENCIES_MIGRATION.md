# Унификация зависимостей серверных компонентов

План миграции к **единому `poetry.lock`** для API, worker, diarization и GigaAM (GPU) без pip-переопределений в Docker.

**Базовая версия Python: 3.12** (`>=3.12,<3.15`) — все образы, локальная разработка, CI и `poetry lock`.

Канон версий: [DEPENDENCIES.md](./DEPENDENCIES.md).

---

## Текущее состояние (2026-06)

| Компонент | Python | Зависимости | Примечание |
|-----------|--------|-------------|------------|
| API / worker CPU | 3.12 | `poetry install --only main` | numpy 2.x, hf_hub 1.x, onnxruntime 1.24.3 |
| worker GPU (GigaAM) | 3.12 | `poetry install --with gigaam` + `install-torch.sh cuda` | единый lock, onnxruntime 1.23.2 |
| diarization CPU/GPU | 3.12 | Poetry `--with diarization` + torch 2.10 cpu/cu128 в Dockerfile | pyannote 4.x, torch 2.10 |

---

## Целевой стек

| Параметр | Значение |
|----------|----------|
| **Python** | **3.12** (`>=3.12,<3.15`) |
| torch / torchaudio | 2.10.* |
| pyannote.audio | 4.x |
| numpy | ≥2.1,<3 |
| huggingface-hub | 1.x |
| onnxruntime | 1.23.2 (GigaAM pin) |
| GigaAM | Poetry group `gigaam` ✅ |

---

## Фазы

### Фаза 0 — Python 3.12 ✅

- [x] `server/pyproject.toml`: `python = ">=3.12,<3.15"`
- [x] Dockerfiles → `python:3.12-slim`
- [x] `poetry.lock` пересобран на 3.12
- [x] Документация: `RELEASE_BUILD_AND_DEPLOY`, `TESTING`, `docker/README`, CLI `>=3.12`
- [x] CI release-artifacts → Python 3.12

---

### Фаза 1 — numpy 2.x ✅

---

### Фаза 2 — Вспомогательные пакеты main ✅

- [x] `onnxruntime = ">=1.24.3,<2"` в main
- [x] `huggingface-hub = "^1.0"` (совместно с diarization после фазы 3)
- [x] `poetry lock` на Python 3.12

---

### Фаза 3 — Diarization → pyannote 4 + torch 2.10 ✅

- [x] Группа `[tool.poetry.group.diarization]`: pyannote-audio ^4, torch/torchaudio ^2.10, hf_hub ^1.0
- [x] `Dockerfile.diarization`: torch 2.10+cpu / 2.10+cu128 вместо 2.8/2.4
- [x] Прогон на реальном аудио (CPU + GPU) на площадке разработки

`pyannote_provider.py` — API `Pipeline.from_pretrained` / `itertracks` на `speaker_diarization` (pyannote 4 `DiarizeOutput`).

---

### Фаза 4 — GigaAM обратно в Poetry lock ✅

- [x] Группа `[tool.poetry.group.gigaam]`: git + `[longform]`, torch ^2.10
- [x] Убран `pip install gigaam` из `Dockerfile.worker.gpu`
- [x] `onnxruntime` в main: `>=1.23,<2` (совместимость с GigaAM)
- [x] Обновлены `GIGAAM_ASR.md`, `ASR_PROVIDER_IMPLEMENTATION.md`, `MODEL_CONFIGURATION.md`

---

### Фаза 5 — Единая установка torch в Docker

#### 5a — скрипт и build-args ✅

- [x] `docker/scripts/install-torch.sh` (`cpu` | `cuda`, `TORCH_VERSION`, индексы `whl/cpu` / `whl/cu128`)
- [x] `TORCH_VERSION` build-arg в `Dockerfile.diarization` и `Dockerfile.worker.gpu`
- [x] Документация в `docker/README.md`, `DEPENDENCIES.md`

#### 5b — ML base-образ ✅

- [x] `docker/Dockerfile.ml-base` — стадии **`ml-base-cpu`** и **`ml-base-cuda`**
- [x] Содержимое base: `python:3.12-slim`, системные пакеты, Poetry, `poetry install` с группами **main + diarization + gigaam**, вызов `install-torch.sh`
- [x] Compose-сервисы `ml-base-cpu` / `ml-base-cuda` (профиль **`ml-base`**), тег `${ML_BASE_TAG:-local}`
- [x] `Dockerfile.diarization` и `Dockerfile.worker.gpu` → `FROM ${ML_BASE_IMAGE}` для registry; compose — **targets** в `Dockerfile.ml-base`
- [x] порядок в `build-docker.*` / `_lib.*` (опционально `ml-base` перед child для отдельных тегов)
- [x] CI: job `ml-base-docker` в `server-deps.yml` (base + smoke child)
- [x] `push-registry.sh`: теги `vt-ml-base-{cpu,cuda}:${TORCH_VERSION}-{variant}-${TAG}`
- [x] Документация: `DEPENDENCIES.md`, `docker/README.md`

**Критерий:** на хосте слои torch совпадают у `worker-final-gpu` и `diarization-worker-gpu` (один pull base, два child-образа с разным `CMD`/очередями).

**Пересборка:** при изменении `server/pyproject.toml`, `poetry.lock`, `Dockerfile.ml-base`, `install-torch.sh` — сначала `ml-base-*`, затем child. При изменении только `server/` в child — достаточно `docker compose build worker-final-gpu` (base из кэша).

---

### Фаза 6 — CI ✅

- [x] `.github/workflows/server-deps.yml`: main + diarization + **gigaam**, import pyannote/gigaam
- [x] job `ml-base-docker`: сборка `ml-base-cpu` / `ml-base-cuda` и smoke child-образов

---

### Фаза 7 — Документация ✅

- [x] `docs/DEPENDENCIES.md`
- [x] Обновлены `RELEASE_BUILD_AND_DEPLOY`, `TESTING`, `docker/README`
- [x] раздел «Образы ML base» в `DEPENDENCIES.md`

---

## Deployment backlog (не блокирует lock)

Варианты развёртывания GPU, не входящие в фазы 0–5. Подробнее: [docker/README.md — GPU deployment modes](../docker/README.md#gpu-deployment-modes-split-vs-unified).

### Опция: unified GPU worker (режим B) ✅

**Статус:** реализовано в compose (профиль **`gpu-unified`**, сервис **`worker-gpu-unified`**).

Цель: один Celery-процесс на одной GPU вместо пары `worker-final-gpu` + `diarization-worker-gpu` — меньше дублирования runtime и проще делить VRAM на одной карте.

- [x] Compose-сервис **`worker-gpu-unified`**, профиль **`gpu-unified`**
- [x] Target **`worker-gpu-unified`** в `Dockerfile.ml-base`; очереди `asr_fast,asr_final,diarization` (`VT_GPU_UNIFIED_WORKER_QUEUES`)
- [x] Взаимоисключение с режимом **split** (`apply_gpu_worker_exclusivity`, `normalize_gpu_compose_profiles`)
- [x] Env **`VT_GPU_DEPLOY_MODE=split|unified`** + профили compose
- [x] `install-or-update.sh`: нормализация профилей и stop split/unified
- [x] Systemd: `docker/systemd/voice-transcriber-worker-gpu-unified.service`
- [x] Документация: [docker/README.md — GPU deployment modes](../docker/README.md#gpu-deployment-modes-split-vs-unified)

**Вне scope backlog:** inference-server (Triton/TorchServe), shared venv volume — не планируются для типового compose-деплоя.

См. также product backlog: [SPEAKER_IDENTIFICATION.md](./SPEAKER_IDENTIFICATION.md) (имена спикеров, LLM + UI).

---

## История плана

| Дата | Изменение |
|------|-----------|
| 2026-06-23 | План; numpy 2.x; цель Python 3.12 |
| 2026-06-23 | **Фазы 4, 5a выполнены**: gigaam в Poetry, `install-torch.sh`, onnxruntime 1.23.2 |
| 2026-06-23 | Фаза 5 → 5a/5b (ml-base); deployment backlog: unified GPU worker |
| 2026-06-24 | **Фаза 5b выполнена**: `Dockerfile.ml-base`, child FROM ml-base, CI `ml-base-docker` |
| 2026-06-24 | **Фаза 3 закрыта**: e2e ASR + diarization на dev (CPU и GPU) |
| 2026-06-24 | **Unified GPU worker**: `worker-gpu-unified`, профиль `gpu-unified`, `VT_GPU_DEPLOY_MODE` |
