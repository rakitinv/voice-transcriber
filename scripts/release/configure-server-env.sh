#!/usr/bin/env bash
# Подготовка /etc/voice-transcriber/voice-transcriber.env на сервере (без секретов в git).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
import_release_env

TARGET="${VT_SERVER_ENV_FILE:-/etc/voice-transcriber/voice-transcriber.env}"
EXAMPLE=""

BUNDLE="${1:-${VT_INSTALL_ROOT:-}}"
if [[ -n "$BUNDLE" && -f "$BUNDLE/deploy/docker/systemd/voice-transcriber.env.example" ]]; then
  EXAMPLE="$BUNDLE/deploy/docker/systemd/voice-transcriber.env.example"
elif [[ -f "$(repo_root)/docker/systemd/voice-transcriber.env.example" ]]; then
  EXAMPLE="$(repo_root)/docker/systemd/voice-transcriber.env.example"
fi

if [[ -z "$EXAMPLE" || ! -f "$EXAMPLE" ]]; then
  echo "Не найден voice-transcriber.env.example" >&2
  exit 1
fi

if [[ -f "$TARGET" ]]; then
  echo "Файл уже существует: $TARGET"
  echo "Отредактируйте вручную или удалите перед повторным копированием."
  exit 0
fi

sudo mkdir -p "$(dirname "$TARGET")"
sudo cp "$EXAMPLE" "$TARGET"
sudo chmod 0640 "$TARGET"
if getent group docker >/dev/null 2>&1; then
  sudo chown root:docker "$TARGET"
  echo "Создан: $TARGET (владелец root:docker, chmod 0640)"
  echo "Пользователь в группе docker сможет читать файл без sudo."
else
  echo "Создан: $TARGET (chmod 0640)"
fi
echo "Отредактируйте VT_JWT_SECRET, VT_DATABASE_URL, VT_S3_*, OAuth и порты."
