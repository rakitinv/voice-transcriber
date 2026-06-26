#!/usr/bin/env bash
# Сборка wheel/sdist CLI — docs/RELEASE_BUILD_AND_DEPLOY.md §4.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
import_release_env

require_cmd python3 "Нужен Python 3.12+."
ROOT="$(repo_root)"

release_step "CLI: pip build (cli/dist/)"
cd "$ROOT/cli"
python3 -m pip install --upgrade pip build
python3 -m build

echo "Артефакты: $ROOT/cli/dist/"
