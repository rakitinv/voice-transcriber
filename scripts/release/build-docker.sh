#!/usr/bin/env bash
# Сборка Docker-образов — docs/RELEASE_BUILD_AND_DEPLOY.md §3.
# Только фронты (без PyPI): build-docker.sh webui admin-webui
# GPU без полного стека: build-docker.sh worker-final-gpu diarization-worker-gpu
# Только ML base: build-docker.sh ml-base-cpu ml-base-cuda  (или VT_DOCKER_COMPOSE_PROFILES=ml-base)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
import_release_env

SKIP_PROFILES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-profiles) SKIP_PROFILES=1; shift ;;
    -*) echo "Неизвестный аргумент: $1" >&2; exit 1 ;;
    *) break ;;
  esac
done

require_cmd docker "Установите Docker Engine."
ROOT="$(repo_root)"
DOCKER_DIR="$ROOT/docker"

release_step "Docker compose build (каталог docker/)"
cd "$DOCKER_DIR"
compose_build_kit_env
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-}"
export VITE_ADMIN_API_BASE_URL="${VITE_ADMIN_API_BASE_URL:-}"
export VITE_PUBLIC_API_BASE_URL="${VITE_PUBLIC_API_BASE_URL:-}"
export VITE_ADMIN_WEBUI_SELF_URL="${VITE_ADMIN_WEBUI_SELF_URL:-}"
export VITE_ADMIN_WEBUI_BASE_PATH="${VITE_ADMIN_WEBUI_BASE_PATH:-}"
export VT_PUBLIC_API_URL="${VT_PUBLIC_API_URL:-}"
export VT_WEBUI_ORIGIN="${VT_WEBUI_ORIGIN:-}"
export VT_ADMIN_WEBUI_ORIGIN="${VT_ADMIN_WEBUI_ORIGIN:-}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-}"

if [[ $# -gt 0 ]]; then
  compose_build_services "$@"
elif [[ "$SKIP_PROFILES" -eq 1 ]]; then
  read -ra default_services <<< "$(compose_default_build_services)"
  compose_build_services "${default_services[@]}"
else
  read -ra default_services <<< "$(compose_default_build_services)"
  compose_build_services "${default_services[@]}"
  mapfile -t optional < <(compose_optional_build_services)
  if ((${#optional[@]})); then
    release_step "Optional compose services: ${optional[*]}"
    compose_build_services "${optional[@]}"
  fi
fi

echo "Готово. Локальные образы: docker images --filter reference=voice-transcriber*"
