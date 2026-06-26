#!/usr/bin/env bash
# Полная сборка: Docker + CLI + расширение + упаковка дистрибутива (Linux / Git Bash).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
import_release_env

SKIP_DOCKER=0 SKIP_CLI=0 SKIP_EXTENSION=0 SKIP_PACKAGE=0 SKIP_PROFILES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-docker) SKIP_DOCKER=1; shift ;;
    --skip-cli) SKIP_CLI=1; shift ;;
    --skip-extension) SKIP_EXTENSION=1; shift ;;
    --skip-package) SKIP_PACKAGE=1; shift ;;
    --skip-profiles) SKIP_PROFILES=1; shift ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 1 ;;
  esac
done

TAG="$(release_tag)"
OUT="$(release_output_dir)"
echo "Релиз: $TAG"
echo "Целевой каталог: $OUT"

if [[ "$SKIP_DOCKER" -eq 0 ]]; then
  if [[ "$SKIP_PROFILES" -eq 1 ]]; then
    bash "$SCRIPT_DIR/build-docker.sh" --skip-profiles
  else
    bash "$SCRIPT_DIR/build-docker.sh"
  fi
fi
[[ "$SKIP_CLI" -eq 1 ]] || bash "$SCRIPT_DIR/build-cli.sh"
[[ "$SKIP_EXTENSION" -eq 1 ]] || bash "$SCRIPT_DIR/build-extension.sh"
[[ "$SKIP_PACKAGE" -eq 1 ]] || bash "$SCRIPT_DIR/package-release.sh"

echo ""
echo "Сборка завершена. Скопируйте на хостинг:"
echo "  $OUT"
