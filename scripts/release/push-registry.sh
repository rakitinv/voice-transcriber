#!/usr/bin/env bash
# Опционально: теги и push образов в registry после сборки (docs §3.2).
# Задайте VT_REGISTRY и VT_REGISTRY_TAG в release.env.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
import_release_env

REGISTRY="${VT_REGISTRY:-}"
TAG="${VT_REGISTRY_TAG:-$(release_tag)}"
ML_BASE_TAG="${ML_BASE_TAG:-local}"
TORCH_VERSION="${TORCH_VERSION:-2.10.0}"

if [[ -z "$REGISTRY" ]]; then
  echo "Задайте VT_REGISTRY в release.env (например registry.example.com/voice-transcriber)" >&2
  exit 1
fi

require_cmd docker ""
ROOT="$(repo_root)"
cd "$ROOT/docker"

release_step "Теги и push в $REGISTRY:$TAG"
mapfile -t IMAGES < <(docker compose config --images | sort -u)
for img in "${IMAGES[@]}"; do
  [[ -z "$img" ]] && continue
  case "$img" in
    postgres:*|redis:*|minio/*) continue ;;
  esac
  # voice-transcriber-api -> vt-api
  short="${img#voice-transcriber-}"
  short="${short%%:*}"
  remote="${REGISTRY}/vt-${short}:${TAG}"
  echo "  $img -> $remote"
  docker tag "$img" "$remote"
  docker push "$remote"
done

# ML base (profile ml-base; может отсутствовать в compose config без --profile ml-base)
for variant in cpu cuda; do
  local_img="voice-transcriber-ml-base-${variant}:${ML_BASE_TAG}"
  if docker image inspect "$local_img" >/dev/null 2>&1; then
    remote="${REGISTRY}/vt-ml-base-${variant}:${TORCH_VERSION}-${variant}-${TAG}"
    echo "  $local_img -> $remote"
    docker tag "$local_img" "$remote"
    docker push "$remote"
    # Удобный плавающий тег для child-образов на площадке
    latest="${REGISTRY}/vt-ml-base-${variant}:latest"
    docker tag "$local_img" "$latest"
    docker push "$latest"
  fi
done

echo "Готово."
