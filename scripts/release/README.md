# Скрипты сборки и развёртывания

Автоматизация [docs/RELEASE_BUILD_AND_DEPLOY.md](../../docs/RELEASE_BUILD_AND_DEPLOY.md): сборка на **сборочной машине** → дистрибутив в каталоге → копирование на **хостинг** → установка/обновление на Linux.

## Быстрый старт

1. Скопируйте `release.env.example` → `release.env` и задайте `VT_RELEASE_TAG` (как в корневом [`VERSION`](../../VERSION), напр. `v0.2.0`), `VT_RELEASE_DIR`, для prod — `VITE_*` URL.
2. **Windows (сборка):** запустите `build-all.bat` (или `build-all.ps1`).
3. Скопируйте каталог `dist/release/voice-transcriber-<tag>/` на сервер.
4. **Linux (хостинг):**
   ```bash
   sudo bash scripts/release/configure-server-env.sh /opt/voice-transcriber-<tag>
   # отредактируйте /etc/voice-transcriber/voice-transcriber.env
   sudo bash scripts/release/install-or-update.sh /opt/voice-transcriber-<tag>
   ```
   Запускайте **`bash`**, не `sh` (скрипт использует bash). В `scripts/release/release.env` на сервере
   переменные с пробелами (`VT_DOCKER_EXTRA_SERVICES`) только **в кавычках** — иначе `source` выполнит
   `worker-final-gpu` как команду. Для установки достаточно `VT_INSTALL_ROOT`, `VT_SERVER_ENV_FILE`,
   `VT_COMPOSE_PROFILES`; строки сборки (`VT_DOCKER_*`) можно закомментировать.

## Скрипты сборки (сборочная машина)

| Скрипт | Назначение |
|--------|------------|
| `build-all.bat` / `build-all.ps1` | Полная сборка + упаковка дистрибутива |
| `build-docker.bat` / `.ps1` / `.sh` | Базовый `docker compose build`, затем только сервисы из `VT_DOCKER_*` / профилей (не весь стек) |
| `build-cli.bat` / `.ps1` / `.sh` | `python -m build` → `cli/dist/` |
| `build-extension.bat` / `.ps1` / `.sh` | `npm ci && npm run build` → `browser-extension/dist/` |
| `package-release.ps1` / `.sh` | Только упаковка (если образы/артефакты уже собраны) |
| `build-all.sh` | То же на Linux / Git Bash |
| `push-registry.sh` | Push в registry вместо tar (опционально) |

## Скрипты на сервере (Linux)

| Скрипт | Назначение |
|--------|------------|
| `install-or-update.sh` | `docker load`, синхронизация в `VT_INSTALL_ROOT`, `compose up -d`, smoke `/health` |
| `configure-server-env.sh` | Создать `/etc/voice-transcriber/voice-transcriber.env` из example |

Если при запуске `*.sh` ошибка `set: pipefail: недопустимое название параметра` или `$'\r': команда не найдена` в `release.env` — окончания строк Windows (CRLF). На сервере: `sed -i 's/\r$//' scripts/release/*.sh scripts/release/release.env 2>/dev/null; true`. Либо удалите `scripts/release/release.env` на хостинге, если не задавали там `VT_INSTALL_ROOT` (скрипты работают и без него).

## Содержимое дистрибутива

- `deploy/docker`, `deploy/configs` — выкат без исходников репозитория
- `docker-images/*.tar` — `docker save` для офлайн/registry-less площадки
- `artifacts/cli` — wheel/sdist
- `artifacts/browser-extension` — `dist/` и zip для пользователей
- `scripts/release/` — установка на сервере

Альтернатива без tar: соберите образы, задайте `VT_REGISTRY` / `VT_REGISTRY_TAG`, выполните `push-registry.sh`, на сервере подтяните образы по тегам (доработка compose под registry — на площадке).

## Makefile

На Linux по-прежнему: `make docker-build`, `make release-artifacts` — см. корневой `Makefile`.
