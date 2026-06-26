#!/usr/bin/env bash
# Упаковка дистрибутива в каталог release (вызывается из build-all.sh).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
import_release_env

SKIP_DOCKER_EXPORT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-docker-export) SKIP_DOCKER_EXPORT=1; shift ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 1 ;;
  esac
done

require_cmd docker ""
ROOT="$(repo_root)"
OUT="$(release_output_dir)"
TAG="$(release_tag)"
DOCKER_DIR="$ROOT/docker"

release_step "Каталог дистрибутива: $OUT"
rm -rf "$OUT"
mkdir -p "$OUT/deploy" "$OUT/artifacts/cli" "$OUT/artifacts/browser-extension"

release_step "Копирование deploy/docker, configs, scripts/release"
cp -a "$ROOT/docker" "$OUT/deploy/"
# Локальный docker/.env (localhost) не должен попадать на сервер — только /etc/voice-transcriber/voice-transcriber.env
rm -f "$OUT/deploy/docker/.env"
cp -a "$ROOT/configs" "$OUT/deploy/"
cp -a "$SCRIPT_DIR" "$OUT/scripts/"

release_step "Публичные URL для сервера (public-urls.env)"
write_public_urls_env "$OUT/deploy/docker/public-urls.env"

if [[ -d "$ROOT/cli/dist" ]]; then
  cp -a "$ROOT/cli/dist/"* "$OUT/artifacts/cli/" 2>/dev/null || true
fi

if [[ -d "$ROOT/browser-extension/dist" ]]; then
  cp -a "$ROOT/browser-extension/dist" "$OUT/artifacts/browser-extension/"
  (cd "$ROOT/browser-extension/dist" && zip -qr "$OUT/artifacts/voice-transcriber-extension-${TAG}.zip" .)
fi

if [[ "$SKIP_DOCKER_EXPORT" -eq 0 ]]; then
  IMG_DIR="$OUT/docker-images"
  mkdir -p "$IMG_DIR"
  release_step "Экспорт образов приложения (docker save, включая compose-профили)"
  cd "$DOCKER_DIR"
  mapfile -t IMAGES < <(compose_collect_export_images "$DOCKER_DIR")
  for img in "${IMAGES[@]}"; do
    [[ -z "$img" ]] && continue
    case "$img" in
      postgres:*|redis:*|minio/*|voice-transcriber-tests*) continue ;;
    esac
    safe="${img//\//_}"
    safe="${safe//:/_}"
    tar="$IMG_DIR/${safe}.tar"
    echo "  save $img -> $tar"
    docker save -o "$tar" "$img"
  done

  if [[ "${VT_EXPORT_INFRA_IMAGES:-}" == "1" ]]; then
    release_step "Экспорт инфраструктурных образов"
    for img in postgres:16-alpine redis:7-alpine minio/minio:latest; do
      if ! docker image inspect "$img" >/dev/null 2>&1; then
        docker pull "$img"
      fi
      safe="infra_${img//\//_}"
      safe="${safe//:/_}"
      docker save -o "$IMG_DIR/${safe}.tar" "$img"
    done
  fi
fi

cat >"$OUT/RELEASE_MANIFEST.json" <<EOF
{
  "product": "voice-transcriber",
  "tag": "$TAG",
  "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "install": "bash scripts/release/install-or-update.sh <this-directory>"
}
EOF

cat >"$OUT/README-DISTRIBUTION.txt" <<EOF
Voice Transcriber — дистрибутив $TAG

1. Скопируйте этот каталог на сервер.
2. Настройте /etc/voice-transcriber/voice-transcriber.env (см. deploy/docker/systemd/).
   Скопируйте URL из deploy/docker/public-urls.env (VT_ADMIN_WEBUI_ORIGIN обязателен для OAuth админки).
3. bash scripts/release/install-or-update.sh <путь-к-этому-каталогу>
   (compose up использует только загруженные образы: --no-build)

Подробности: docs/RELEASE_BUILD_AND_DEPLOY.md
EOF

echo ""
echo "Дистрибутив собран: $OUT"
