#!/usr/bin/env bash
# Production-сборка расширения — docs/RELEASE_BUILD_AND_DEPLOY.md §5.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
import_release_env

require_cmd npm "Установите Node.js 22."
ROOT="$(repo_root)"

# Compile-time default for fresh installs (see browser-extension/src/settings/storage.ts).
if [[ -z "${VITE_DEFAULT_SERVER_URL:-}" && -n "${VT_PUBLIC_API_URL:-}" ]]; then
  export VITE_DEFAULT_SERVER_URL="${VT_PUBLIC_API_URL}"
fi
if [[ -n "${VITE_DEFAULT_SERVER_URL:-}" ]]; then
  echo "VITE_DEFAULT_SERVER_URL=${VITE_DEFAULT_SERVER_URL}"
fi

release_step "Browser extension: npm ci && npm run build"
cd "$ROOT/browser-extension"
npm ci
npm run build

echo "Артефакты: $ROOT/browser-extension/dist/"
