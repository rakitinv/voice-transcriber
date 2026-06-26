#!/usr/bin/env bash
# Установка или обновление серверного стека на Linux-хостинге из дистрибутива.
# Использование:
#   bash install-or-update.sh /path/to/voice-transcriber-<tag>
#   bash install-or-update.sh   # каталог = VT_INSTALL_ROOT или текущий родитель deploy/
#
# Требования: Docker, Docker Compose v2, bash.
# См. docs/RELEASE_BUILD_AND_DEPLOY.md §3.4–3.6, docker/README.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
import_release_env

BUNDLE_DIR=""
LOAD_ONLY=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Установка / обновление Voice Transcriber на сервере.

  install-or-update.sh [OPTIONS] [BUNDLE_DIR]

  BUNDLE_DIR — распакованный дистрибутив (с deploy/docker, docker-images/, …).
               По умолчанию: аргумент, затем VT_INSTALL_ROOT, затем родитель scripts/release.

Опции:
  --load-only   Только docker load образов, без compose up
  --dry-run     Показать действия без выполнения
  -h, --help    Справка

Перед первым запуском:
  sudo mkdir -p /etc/voice-transcriber
  sudo cp deploy/docker/systemd/voice-transcriber.env.example /etc/voice-transcriber/voice-transcriber.env
  # отредактируйте VT_JWT_SECRET, VT_DATABASE_URL, VT_S3_*, OAuth;
  # VT_ADMIN_WEBUI_ORIGIN и др. URL — в voice-transcriber.env (см. deploy/docker/public-urls.env)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --load-only) LOAD_ONLY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "Неизвестная опция: $1" >&2; usage; exit 1 ;;
    *)
      if [[ -n "$BUNDLE_DIR" ]]; then
        echo "Лишний аргумент: $1" >&2
        exit 1
      fi
      BUNDLE_DIR="$1"
      shift
      ;;
  esac
done

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

resolve_bundle_dir() {
  if [[ -n "$BUNDLE_DIR" ]]; then
    echo "$(cd "$BUNDLE_DIR" && pwd)"
    return
  fi
  # dist layout: <bundle>/scripts/release/install-or-update.sh
  local parent
  parent="$(cd "$SCRIPT_DIR/../.." && pwd)"
  if [[ -d "$parent/deploy/docker" ]]; then
    echo "$parent"
    return
  fi
  if [[ -n "${VT_INSTALL_ROOT:-}" && -d "${VT_INSTALL_ROOT}/deploy/docker" ]]; then
    echo "$(cd "$VT_INSTALL_ROOT" && pwd)"
    return
  fi
  if [[ -n "${VT_INSTALL_ROOT:-}" ]]; then
    echo "Каталог VT_INSTALL_ROOT не найден или без deploy/docker: ${VT_INSTALL_ROOT}" >&2
    echo "Укажите путь к дистрибутиву: bash install-or-update.sh /path/to/voice-transcriber-<tag>" >&2
    exit 1
  fi
  echo "Укажите BUNDLE_DIR или задайте VT_INSTALL_ROOT в release.env" >&2
  exit 1
}

require_cmd docker ""
require_cmd docker "Нужен docker compose (плагин v2)."

BUNDLE="$(resolve_bundle_dir)"
INSTALL_ROOT="${VT_INSTALL_ROOT:-$BUNDLE}"
ENV_FILE="${VT_SERVER_ENV_FILE:-/etc/voice-transcriber/voice-transcriber.env}"

if [[ ! -f "$BUNDLE/deploy/docker/docker-compose.yml" ]]; then
  echo "Не найден compose: $BUNDLE/deploy/docker/docker-compose.yml" >&2
  echo "Проверьте BUNDLE_DIR ($BUNDLE) и структуру дистрибутива." >&2
  echo "Ожидается каталог вида voice-transcriber-<tag>/ с deploy/docker/, docker-images/, scripts/release/." >&2
  exit 1
fi

DOCKER_COMPOSE_DIR="$INSTALL_ROOT/deploy/docker"
if [[ "$BUNDLE" == "$INSTALL_ROOT" && ! -f "$DOCKER_COMPOSE_DIR/docker-compose.yml" ]]; then
  echo "Не найден compose: $DOCKER_COMPOSE_DIR/docker-compose.yml" >&2
  echo "Проверьте BUNDLE_DIR ($BUNDLE) и структуру дистрибутива." >&2
  exit 1
fi

release_step "Дистрибутив: $BUNDLE"
release_step "Установка в: $INSTALL_ROOT"
release_step "Compose: $DOCKER_COMPOSE_DIR"

if [[ "$BUNDLE" != "$INSTALL_ROOT" ]]; then
  release_step "Синхронизация файлов в $INSTALL_ROOT"
  run sudo mkdir -p "$INSTALL_ROOT"
  if command -v rsync >/dev/null 2>&1; then
    run sudo rsync -a --delete "$BUNDLE/" "$INSTALL_ROOT/"
  else
    run sudo rm -rf "${INSTALL_ROOT:?}"/*
    run sudo cp -a "$BUNDLE/." "$INSTALL_ROOT/"
  fi
  DOCKER_COMPOSE_DIR="$INSTALL_ROOT/deploy/docker"
fi

IMG_DIR="$INSTALL_ROOT/docker-images"
if [[ -d "$IMG_DIR" ]]; then
  release_step "Загрузка образов (docker load)"
  shopt -s nullglob
  for tar in "$IMG_DIR"/*.tar; do
    echo "  load $(basename "$tar")"
    run docker load -i "$tar"
  done
  shopt -u nullglob
else
  echo "Каталог docker-images/ отсутствует — предполагается, что образы уже в registry или собраны на хосте."
fi

if [[ "$LOAD_ONLY" -eq 1 ]]; then
  echo "Режим --load-only: compose up пропущен."
  exit 0
fi

COMPOSE_ARGS=()
merge_compose_profiles "$ENV_FILE"
normalize_gpu_compose_profiles "$ENV_FILE"
if [[ -n "${VT_COMPOSE_PROFILES:-}" ]]; then
  IFS=',' read -ra PROFS <<< "$VT_COMPOSE_PROFILES"
  for p in "${PROFS[@]}"; do
    p="${p// /}"
    [[ -n "$p" ]] && COMPOSE_ARGS+=(--profile "$p")
  done
fi

ENV_ARGS=()
COMPOSE=(docker compose)
if [[ -f "$ENV_FILE" ]]; then
  release_step "Переменные окружения: $ENV_FILE"
  ENV_ARGS=(--env-file "$ENV_FILE")
  if [[ ! -r "$ENV_FILE" && "$(id -u)" -ne 0 ]]; then
    echo "Нет чтения $ENV_FILE (обычно chmod 0640 root). Запуск compose через sudo." >&2
    echo "  Либо: sudo chown root:docker $ENV_FILE && usermod -aG docker \$USER" >&2
    COMPOSE=(sudo docker compose)
  fi
else
  echo "Предупреждение: $ENV_FILE не найден. Используются значения по умолчанию из compose." >&2
  echo "  Создайте файл из deploy/docker/systemd/voice-transcriber.env.example" >&2
fi

HINTS_FILE="$DOCKER_COMPOSE_DIR/public-urls.env"
warn_if_admin_oauth_env_missing "$ENV_FILE" "$HINTS_FILE"

if [[ -f "$ENV_FILE" ]]; then
  release_step "Копирование серверного конфига в deploy/docker/.env (для compose env_file)"
  COMPOSE_DOTENV="$DOCKER_COMPOSE_DIR/.env"
  if [[ -e "$COMPOSE_DOTENV" && ! -L "$COMPOSE_DOTENV" ]]; then
    if grep -qE '^VT_ADMIN_WEBUI_ORIGIN=http://localhost' "$COMPOSE_DOTENV" 2>/dev/null; then
      echo "  Заменяем устаревший $COMPOSE_DOTENV (localhost из дистрибутива/сборки)" >&2
      run rm -f "$COMPOSE_DOTENV"
    fi
  elif [[ -L "$COMPOSE_DOTENV" ]]; then
    echo "  Удаляем symlink $COMPOSE_DOTENV (Docker env_file надёжнее с обычным файлом)" >&2
    run rm -f "$COMPOSE_DOTENV"
  fi
  sync_compose_dotenv_from_server "$DOCKER_COMPOSE_DIR" "$ENV_FILE"
fi

release_step "Миграции и запуск стека (compose up -d)"
cd "$DOCKER_COMPOSE_DIR"
# migrate выполняется до api по depends_on; up -d поднимает весь стек.
# На хостинге нет server/ — только docker load; сборка из deploy/ невозможна.
run "${COMPOSE[@]}" "${ENV_ARGS[@]}" "${COMPOSE_ARGS[@]}" up -d --no-build

apply_gpu_worker_exclusivity "$DOCKER_COMPOSE_DIR" "${COMPOSE[@]}" "${ENV_ARGS[@]}"

if [[ "$DRY_RUN" -eq 0 && -f "$ENV_FILE" ]]; then
  verify_api_admin_oauth_env_in_container "$DOCKER_COMPOSE_DIR" "${COMPOSE[@]}" "${ENV_ARGS[@]}" || true
fi

release_step "Проверка health (ожидание api)"
if [[ "$DRY_RUN" -eq 0 ]]; then
  API_PORT="${API_PUBLISH_PORT:-8002}"
  for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
      echo "API health: OK (http://127.0.0.1:${API_PORT}/health)"
      break
    fi
    if [[ "$i" -eq 30 ]]; then
      echo "Предупреждение: /health не ответил за 30 попыток. Проверьте: docker compose ps" >&2
    fi
    sleep 2
  done
fi

echo ""
echo "Установка/обновление завершено."
if [[ "${COMPOSE[0]}" == "sudo" ]]; then
  echo "  compose: cd $DOCKER_COMPOSE_DIR && sudo docker compose --env-file $ENV_FILE ps"
  echo "  логи:    sudo docker compose --env-file $ENV_FILE logs -f api worker"
else
  echo "  compose: cd $DOCKER_COMPOSE_DIR && docker compose ps"
  echo "  логи:    docker compose logs -f api worker"
fi
