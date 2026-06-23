#!/usr/bin/env bash
# Sync root VERSION into pyproject.toml and package.json files.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_FILE="$ROOT/VERSION"
if [[ ! -f "$VERSION_FILE" ]]; then
  echo "VERSION file not found: $VERSION_FILE" >&2
  exit 1
fi
VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
  echo "VERSION must be SemVer (e.g. 0.2.0): got '$VERSION'" >&2
  exit 1
fi

set_pyproject() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  if sed -i.bak "s/^version = \".*\"/version = \"$VERSION\"/" "$f" 2>/dev/null; then
    rm -f "${f}.bak"
  else
    # macOS sed
    sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/" "$f"
  fi
  echo "Updated $f -> $VERSION"
}

set_package_json() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  if sed -i.bak -E "s/^(\"version\"[[:space:]]*:[[:space:]]*\")[^\"]*(\")/\1${VERSION}\2/" "$f" 2>/dev/null; then
    rm -f "${f}.bak"
  else
    sed -i '' -E "s/^(\"version\"[[:space:]]*:[[:space:]]*\")[^\"]*(\")/\1${VERSION}\2/" "$f"
  fi
  echo "Updated $f -> $VERSION"
}

set_pyproject "$ROOT/server/pyproject.toml"
set_pyproject "$ROOT/cli/pyproject.toml"
set_package_json "$ROOT/webui/package.json"
set_package_json "$ROOT/admin-webui/package.json"
set_package_json "$ROOT/browser-extension/package.json"

echo "VERSION $VERSION synced."
